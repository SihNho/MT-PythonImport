// cal_file.inc - included at the end of mt_track.cu.  Calibration straight from the LabVIEW .cal file, so the wrapper VI needs
// no 'Array Cal Cluster' wire (wiring the nested-handle cluster array into the adapt-to-type CLFN sent LabVIEW 2026 into a
// 100 %-CPU spin, 2026-09-08 08:43).  Layout (flattened LabVIEW data, big-endian; tools/gpu/fixture.py read_cal):
//   [I32 n][I32 2] n x 2 DBL bead x,y ; [I32 n][I32 S][I32 L] n x S x L DBL mirrored radial profiles (L = 2*half - 1) ;
//   [I32 S][I32 n][I32 3] n x (LOW, HIGH, forget) I32 ; DBL z step ; ...
// Per bead (= the loader VIs, checked against LabVIEW's own clusters: cosband 8.8e-8, real/ampl/cork <= 6.7e-7, z 4.7e-9 um):
//   cosband[i] = 0.5 (1 - cos(2 pi (i-LOW)/(HIGH-LOW))) for LOW <= i <= HIGH else 0        (length cross; [0, L) used)
//   per slice  c = IFFT(FFT(row) * cosband[:L]) ; cork = c[half-1+forget :] ; real = Re(cork) ; ampl = |cork|
// DFTs are done on the host in double (O(L^2) per slice, 5 beads x 60 slices x 119^2 = 4 M multiply-adds: milliseconds).
static uint32_t be32(const unsigned char* p) { return ((uint32_t)p[0] << 24) | ((uint32_t)p[1] << 16) | ((uint32_t)p[2] << 8) | p[3]; }
static double be64(const unsigned char* p) { uint64_t v = 0; for (int i = 0; i < 8; i++) v = (v << 8) | p[i]; double d; memcpy(&d, &v, 8); return d; }

static int cal_file_header(const char* path, int* n_out, int* S_out, int* L_out) {
    FILE* f = fopen(path, "rb"); if (!f) { snprintf(g_err, sizeof g_err, "cal file not found"); return -1; }
    unsigned char hdr[12];
    if (fread(hdr, 1, 8, f) != 8) { fclose(f); snprintf(g_err, sizeof g_err, "cal header"); return -1; }
    int n = (int)be32(hdr), m = (int)be32(hdr + 4);
    if (fseek(f, 8L * n * m, SEEK_CUR) != 0 || fread(hdr, 1, 12, f) != 12) { fclose(f); snprintf(g_err, sizeof g_err, "cal header 2"); return -1; }
    fclose(f); *n_out = n; *S_out = (int)be32(hdr + 4); *L_out = (int)be32(hdr + 8); return 0;
}

static int load_cal_file(void* handle, const char* path, int cross, int* nb_out, double* zstep_out) {
    Ctx* c = (Ctx*)handle; int half = c->half; int L = 2 * half - 1;
    FILE* f = fopen(path, "rb"); if (!f) { snprintf(g_err, sizeof g_err, "cal file not found"); return -1; }
    fseek(f, 0, SEEK_END); long sz = ftell(f); fseek(f, 0, SEEK_SET);
    unsigned char* b = (unsigned char*)malloc(sz);
    if (fread(b, 1, sz, f) != (size_t)sz) { fclose(f); free(b); snprintf(g_err, sizeof g_err, "cal read"); return -1; }
    fclose(f);
    long o = 0; int n = (int)be32(b + o); int m = (int)be32(b + o + 4); o += 8 + 8L * n * m;
    int n2 = (int)be32(b + o), S = (int)be32(b + o + 4), Lf = (int)be32(b + o + 8); o += 12;
    if (n2 != n || Lf != L || S != c->S || n > c->nb_alloc) {
        snprintf(g_err, sizeof g_err, "cal layout n=%d S=%d L=%d (ctx S=%d half=%d nb=%d)", n, S, Lf, c->S, half, c->nb_alloc); free(b); return -1;
    }
    const unsigned char* stack = b + o; o += 8L * n * S * L;
    int Sf = (int)be32(b + o); int nn = (int)be32(b + o + 4); int three = (int)be32(b + o + 8); o += 12;
    if (Sf != S || nn != n || three != 3) { snprintf(g_err, sizeof g_err, "cal tail layout"); free(b); return -1; }
    const unsigned char* tri = b + o; o += 12L * n; double zstep = be64(b + o);
    double* cb = (double*)malloc(cross * sizeof(double));
    double* cosre = (double*)malloc(L * sizeof(double)); double* cosim = (double*)malloc(L * sizeof(double));
    for (int k = 0; k < L; k++) { cosre[k] = cos(2 * M_PI * k / L); cosim[k] = -sin(2 * M_PI * k / L); }   // exp(-2 pi i k/L)
    double* row = (double*)malloc(L * sizeof(double)); double* Fr = (double*)malloc(L * sizeof(double)); double* Fi = (double*)malloc(L * sizeof(double));
    int rc = 0;
    for (int bead = 0; bead < n && rc == 0; bead++) {
        int lo = (int)be32(tri + 12 * bead), hi = (int)be32(tri + 12 * bead + 4), forget = (int)be32(tri + 12 * bead + 8);
        for (int i = 0; i < cross; i++) cb[i] = (i >= lo && i <= hi) ? 0.5 * (1 - cos(2 * M_PI * (double)(i - lo) / (hi - lo))) : 0.0;
        int len = half - forget;
        double* real = (double*)malloc((size_t)S * len * sizeof(double)); double* ampl = (double*)malloc((size_t)S * len * sizeof(double));
        double* cre = (double*)malloc((size_t)S * len * sizeof(double)); double* cim = (double*)malloc((size_t)S * len * sizeof(double));
        for (int s = 0; s < S; s++) {
            const unsigned char* rp = stack + 8L * ((long)bead * S * L + (long)s * L);
            for (int t = 0; t < L; t++) row[t] = be64(rp + 8 * t);
            for (int k = 0; k < L; k++) {                                     // forward DFT of the real row, times the band
                double sr = 0, si = 0;
                for (int t = 0; t < L; t++) { int idx = (int)(((long)k * t) % L); sr += row[t] * cosre[idx]; si += row[t] * cosim[idx]; }
                Fr[k] = sr * cb[k]; Fi[k] = si * cb[k];
            }
            for (int r = forget; r < half; r++) {                             // inverse DFT at the needed indices only
                int q = half - 1 + r; double sr = 0, si = 0;
                for (int k = 0; k < L; k++) {                                 // exp(+2 pi i k q / L) = (cr, ci)
                    int idx = (int)(((long)k * q) % L); double cr = cosre[idx], ci = -cosim[idx];
                    sr += Fr[k] * cr - Fi[k] * ci; si += Fr[k] * ci + Fi[k] * cr;
                }
                sr /= L; si /= L; int j = r - forget;
                real[s * len + j] = sr; cre[s * len + j] = sr; cim[s * len + j] = si; ampl[s * len + j] = sqrt(sr * sr + si * si);
            }
        }
        rc = mt_gpu_set_bead(handle, bead, forget, zstep, cb, nullptr, real, ampl, cre, cim, len);
        free(real); free(ampl); free(cre); free(cim);
    }
    free(cb); free(cosre); free(cosim); free(row); free(Fr); free(Fi); free(b);
    if (rc == 0) { *nb_out = n; *zstep_out = zstep; }
    return rc;
}

// Entry WITHOUT a cluster array: the calibration file path arrives in `text` (the C-string parameter; the status overwrites it on
// return - the wrapper must pass a string of at least 60 bytes, a full path always is).  Loaded once per (path, cross).
static char g_calpath[1024] = "";
API int GPUTracking_file(int threads, int DIM1, int DIM2, int DIM3, int DIM4, LvArrI32** x, LvArrI32** y, int cross, int crossthickness,
                         LvArr2U8** image, LvArr2F** xout, LvArr2F** yout, LvArr2F** zout, void** calibration, LvArrU8** BeadStatus,
                         char* text, LvArr1F** test) {
    (void)threads; (void)DIM1; (void)DIM2; (void)DIM3; (void)DIM4; (void)crossthickness; (void)yout; (void)zout;
    dump_all((void**)x, (void**)y, (void**)image, (void**)xout, (void**)yout, (void**)zout, calibration, (void**)BeadStatus, text, (void**)test, cross);
    int nb = 0, rc = check_common(x, y, image, xout, BeadStatus, text, test, cross, &nb); if (rc) return rc;
    char path[1024]; strncpy(path, text, 1023); path[1023] = 0;
    for (int i = (int)strlen(path) - 1; i >= 0 && (path[i] == ' ' || path[i] == '\r' || path[i] == '\n'); i--) path[i] = 0;
    if (!g_ctx || strcmp(path, g_calpath) != 0 || g_cross != cross) {
        if (g_ctx) { mt_gpu_free(g_ctx); g_ctx = nullptr; }
        int n = 0, S = 0, L = 0;
        if (cal_file_header(path, &n, &S, &L) != 0) { strncpy(text, g_err, 59); text[59] = 0; return -12; }
        double wh[CROSS_MAX]; make_win_h(cross, wh); double* wrs = to_double((*test)->d, cross);
        int rc2 = mt_gpu_init(cross, S, n, wrs, wh, &g_ctx); free(wrs);
        if (rc2 != 0) { strncpy(text, g_err, 59); text[59] = 0; return -12; }
        int nb_file = 0; double zs = 0;
        if (load_cal_file(g_ctx, path, cross, &nb_file, &zs) != 0) { strncpy(text, g_err, 59); text[59] = 0; mt_gpu_free(g_ctx); g_ctx = nullptr; return -13; }
        g_nb = nb_file; g_cross = cross; g_S = S; g_calsig = 0; strncpy(g_calpath, path, 1023); g_calpath[1023] = 0;
    }
    if (nb != g_nb) { snprintf(text, 60, "nb %d != cal beads %d", nb, g_nb); return -14; }
    return run_track(nb, x, image, xout, y, BeadStatus, text);
}

// The donor's decorated export resolves here: cluster route when a non-empty cluster array is wired, file route otherwise.
API int GPUTracking_auto(int threads, int DIM1, int DIM2, int DIM3, int DIM4, LvArrI32** x, LvArrI32** y, int cross, int crossthickness,
                         LvArr2U8** image, LvArr2F** xout, LvArr2F** yout, LvArr2F** zout, LvCalArr** calibration, LvArrU8** BeadStatus,
                         char* text, LvArr1F** test) {
    if (calibration && *calibration && (*calibration)->n > 0)
        return GPUTracking_lv(threads, DIM1, DIM2, DIM3, DIM4, x, y, cross, crossthickness, image, xout, yout, zout, calibration, BeadStatus, text, test);
    return GPUTracking_file(threads, DIM1, DIM2, DIM3, DIM4, x, y, cross, crossthickness, image, xout, yout, zout, (void**)calibration, BeadStatus, text, test);
}
