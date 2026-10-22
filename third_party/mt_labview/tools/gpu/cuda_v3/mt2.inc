// mt2.inc - GPU tracking interface v2 (2026-09-09, our design; see docs/gpu-backend.md "GPU interface v2").
//   ctx = mt2_open(cal_path, cross, flags, status, len)        calibration + windows to the GPU once, buffers allocated once
//   mt2_set_image(ctx, pixel_ptr, line_width, width, height)  IMAQ buffer pointer (no LabVIEW copy); pinned on first use
//   mt2_track(ctx, nb, xyz_in[3nb], good_in[nb], xyz_out[3nb], idx_out[nb], good_out[nb], status, len)   one launch per frame
//   mt2_close(ctx)
// Numerics: identical to GPUTracking_* (same Ctx, same fused kernel); x,y in are DBL and rounded half-to-even like the
// kernel VI's I32 coercion.  Status strings: "No_Errors t=.. u=.. k=.. e=.." or the error text (<= status_len - 1 bytes).
struct Mt2 {
    void* h;                       // Ctx*
    int cross, nb, S; double zstep;
    const unsigned char* pix; int line_width, width, height;
    unsigned char* stage; size_t stage_bytes;   // DLL-owned PINNED staging buffer (never pin LabVIEW's IMAQ buffer: IMAQ may free/re-allocate it
                                                // under the registration -> stale pages and per-frame register churn, seen 2026-09-09 13:2x)
    int keepalive;
    struct Mt2Host* host;          // v2: the calibration arrays exactly as given to mt2_open_arrays (nullptr on the file route)
};

static void mt2_status(char* status, int len, const char* text) { if (status && len > 0) { strncpy(status, text, len - 1); status[len - 1] = 0; } }

// Per-frame timing to a file, enabled by the environment variable MT_GPU_LOG=<path>.  The LabVIEW subVI calls with
// status_len 0 (no status buffer of its own), so this is the only way to see the DLL's own time from inside the main VI.
static FILE* g_mt2_log = nullptr; static int g_mt2_log_tried = 0;
static void mt2_log(LARGE_INTEGER t0, LARGE_INTEGER t1, long long freq) {
    if (!g_mt2_log_tried) {
        g_mt2_log_tried = 1;
        const char* p = getenv("MT_GPU_LOG");
        if (p && *p) g_mt2_log = fopen(p, "a");
    }
    if (!g_mt2_log) return;
    fprintf(g_mt2_log, "%.3f %.3f %.3f %.3f\n", 1e3 * (double)(t1.QuadPart - t0.QuadPart) / (double)freq, g_t_up, g_t_gpu, g_t_ev);
    fflush(g_mt2_log);
}

// Single-context policy (2026-09-09, user: the experiment VI is normally stopped with LabVIEW's Abort button, so mt2_close never
// runs and the next open would leak the previous GPU allocation).  mt2_open closes any context this DLL still holds before making
// a new one; the rig runs exactly one tracking loop, so nothing legitimate is ever closed by this.
static long long g_mt2_live = 0;
static long long g_mt2_ctx = 0; static char g_mt2_path[1024] = "";          // the one-node entry's cached context (mt2_track_simple)

API int mt2_close(long long ctx);

API long long mt2_open(const char* cal_path, int cross, int flags, char* status, int status_len) {
    if (!cal_path || cross <= 0 || cross > CROSS_MAX) { mt2_status(status, status_len, "mt2_open: bad arguments"); return 0; }
    if (g_mt2_live) { mt2_close(g_mt2_live); g_mt2_live = 0; }              // an aborted run's context, if any
    int n = 0, S = 0, L = 0;
    if (cal_file_header(cal_path, &n, &S, &L) != 0) { mt2_status(status, status_len, g_err); return 0; }
    if (L != 2 * (cross / 2) - 1) { snprintf(g_err, sizeof g_err, "mt2_open: cal profile length %d != 2*half-1 for cross %d", L, cross); mt2_status(status, status_len, g_err); return 0; }
    double wrs[CROSS_MAX], wh[CROSS_MAX]; make_win_rs(cross, wrs); make_win_h(cross, wh);
    void* h = nullptr;
    if (mt_gpu_init(cross, S, n, wrs, wh, &h) != 0) { mt2_status(status, status_len, g_err); return 0; }
    int nb_file = 0; double zs = 0;
    if (load_cal_file(h, cal_path, cross, &nb_file, &zs) != 0) { mt2_status(status, status_len, g_err); mt_gpu_free(h); return 0; }
    Mt2* m = (Mt2*)calloc(1, sizeof(Mt2)); m->h = h; m->cross = cross; m->nb = nb_file; m->S = S; m->zstep = zs; m->keepalive = flags & 1;
    if (m->keepalive) mt_gpu_keepalive(1);
    snprintf(g_err, sizeof g_err, "No_Errors beads=%d slices=%d zstep=%.4g", nb_file, S, zs); mt2_status(status, status_len, g_err);
    g_mt2_live = (long long)(intptr_t)m;
    return g_mt2_live;
}

API int mt2_set_image(long long ctx, unsigned long long pixel_ptr, int line_width, int width, int height) {
    Mt2* m = (Mt2*)(intptr_t)ctx; if (!m || !pixel_ptr || width <= 0 || height <= 0 || line_width < width) return -1;
    const unsigned char* p = (const unsigned char*)(uintptr_t)pixel_ptr;
    size_t need = (size_t)width * height;
    if (need != m->stage_bytes) {                                          // packed pinned staging buffer, (re)allocated on a size change only
        if (m->stage) cudaFreeHost(m->stage);
        m->stage = nullptr; m->stage_bytes = 0;
        if (cudaMallocHost((void**)&m->stage, need) != cudaSuccess) { cudaGetLastError(); m->stage = nullptr; } else m->stage_bytes = need;
    }
    m->pix = p; m->line_width = line_width; m->width = width; m->height = height; return 0;
}

API int mt2_track(long long ctx, int nb, const double* xyz_in, const unsigned char* good_in, double* xyz_out, int* idx_out, unsigned char* good_out,
                  char* status, int status_len) {
    Mt2* m = (Mt2*)(intptr_t)ctx;
    if (!m || !xyz_in || !xyz_out || !idx_out || !good_out) { mt2_status(status, status_len, "mt2_track: null argument"); return -10; }
    if (!m->pix) { mt2_status(status, status_len, "mt2_track: no image (call mt2_set_image)"); return -11; }
    if (nb <= 0) nb = m->nb;                                               // 0 = "as many beads as the calibration has": lets the LabVIEW
                                                                           // subVI leave the terminal at its default instead of computing a size
    if (nb != m->nb) { snprintf(g_err, sizeof g_err, "mt2_track: nb %d != calibration beads %d", nb, m->nb); mt2_status(status, status_len, g_err); return -12; }
    mt_gpu_keepalive_touch();                                              // the keep-alive thread parks itself if this stops arriving
    Ctx* c = (Ctx*)m->h; size_t bytes = (size_t)m->height * m->width;
    LARGE_INTEGER f0, t0, t1; QueryPerformanceFrequency(&f0); QueryPerformanceCounter(&t0);
    if (bytes != c->img_bytes) { if (c->d_img) cudaFree(c->d_img); if (cudaMalloc(&c->d_img, bytes) != cudaSuccess) { mt2_status(status, status_len, "cudaMalloc image"); return -13; } c->img_bytes = bytes; }
    // strided IMAQ rows -> packed PINNED staging buffer (host memcpy, ~0.1 ms) -> one DMA; falls back to a pageable 2-D copy
    LARGE_INTEGER tu0, tu1; QueryPerformanceCounter(&tu0);
    if (m->stage) {
        for (int r = 0; r < m->height; r++) memcpy(m->stage + (size_t)r * m->width, m->pix + (size_t)r * m->line_width, m->width);
        if (cudaMemcpy(c->d_img, m->stage, bytes, cudaMemcpyHostToDevice) != cudaSuccess) { mt2_status(status, status_len, "cudaMemcpy image"); return -14; }
    } else if (cudaMemcpy2D(c->d_img, m->width, m->pix, m->line_width, m->width, m->height, cudaMemcpyHostToDevice) != cudaSuccess) { mt2_status(status, status_len, "cudaMemcpy2D image"); return -14; }
    QueryPerformanceCounter(&tu1); g_t_up = 1e3 * (double)(tu1.QuadPart - tu0.QuadPart) / (double)f0.QuadPart;
    int* xi = (int*)malloc(nb * sizeof(int)); int* yi = (int*)malloc(nb * sizeof(int)); int* gi = (int*)malloc(nb * sizeof(int));
    double* xo = (double*)malloc(nb * sizeof(double)); double* yo = (double*)malloc(nb * sizeof(double)); double* zo = (double*)malloc(nb * sizeof(double)); int* go = (int*)malloc(nb * sizeof(int));
    for (int b = 0; b < nb; b++) { xi[b] = (int)rint(xyz_in[3 * b]); yi[b] = (int)rint(xyz_in[3 * b + 1]); gi[b] = good_in ? (good_in[b] ? 1 : 0) : 1; }
    int rc = mt_gpu_track_fused_dev(m->h, m->height, m->width, nb, xi, yi, gi, xo, yo, zo, idx_out, go);   // (H, W)   // image already on the device
    if (rc == 0) {
        for (int b = 0; b < nb; b++) { xyz_out[3 * b] = xo[b]; xyz_out[3 * b + 1] = yo[b]; xyz_out[3 * b + 2] = zo[b]; good_out[b] = (unsigned char)(go[b] ? 1 : 0); }
        QueryPerformanceCounter(&t1);
        snprintf(g_err, sizeof g_err, "No_Errors t=%.2f u=%.2f k=%.2f e=%.2f", 1e3 * (double)(t1.QuadPart - t0.QuadPart) / (double)f0.QuadPart, g_t_up, g_t_gpu, g_t_ev);
    }
    mt2_status(status, status_len, g_err);
    mt2_log(t0, t1, f0.QuadPart);                                          // MT_GPU_LOG=<file>: per-frame timing even when the
                                                                           // caller passes status_len 0 (the LabVIEW subVI does)
    free(xi); free(yi); free(gi); free(xo); free(yo); free(zo); free(go);
    return rc;
}

static void mt2_host_free(struct Mt2Host* H);
API int mt2_close(long long ctx) {
    Mt2* m = (Mt2*)(intptr_t)ctx; if (!m) return -1;
    if (m->keepalive) mt_gpu_keepalive(0);
    if (m->host) { mt2_host_free(m->host); m->host = nullptr; }
    if (m->stage) cudaFreeHost(m->stage);
    if (g_mt2_live == ctx) g_mt2_live = 0;
    if (g_mt2_ctx == ctx) { g_mt2_ctx = 0; g_mt2_path[0] = 0; }             // the one-node entry's cache points here too
    mt_gpu_free(m->h); free(m); return 0;
}

// One-node convenience entry for the LabVIEW subVI: the DLL opens and caches the context by calibration path, registers the
// IMAQ buffer, tracks.  Parameters are plain C types (the scripted CLFN is configured to exactly these):
//   const char* cal_path | uint64 pixel_ptr | int line_width_bytes | int width | int height | int nb |
//   const double* xyz_in[3nb] | const uint8* good_in[nb] | double* xyz_out[3nb] | int32* idx_out[nb] | uint8* good_out[nb] |
//   char* status (>= 64 bytes) | int status_len | int flags (bit0 keep-alive)    -> int rc (0 = ok)
// Where the calibration path comes from when the LabVIEW subVI leaves the terminal empty (2026-09-09): the environment variable
// MT_GPU_CAL, else a one-line text file `mt_track_cal.txt` beside the DLL.  This keeps the drop-in subVI free of a mandatory new
// pane input; wiring a real path from the caller always wins over both fallbacks.
static const char* mt2_cal_fallback() {
    static char buf[1024];
    const char* env = getenv("MT_GPU_CAL");
    if (env && *env) { strncpy(buf, env, sizeof buf - 1); buf[sizeof buf - 1] = 0; return buf; }
    char dll[1024] = ""; HMODULE h = nullptr;
    if (GetModuleHandleExA(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT, (LPCSTR)&mt2_cal_fallback, &h) && h
        && GetModuleFileNameA(h, dll, sizeof dll)) {
        char* slash = strrchr(dll, '\\');
        if (slash) { slash[1] = 0; strncat(dll, "mt_track_cal.txt", sizeof dll - strlen(dll) - 1); }
        FILE* f = fopen(dll, "rb");
        if (f) {
            size_t n = fread(buf, 1, sizeof buf - 1, f); fclose(f); buf[n] = 0;
            while (n && (buf[n - 1] == '\n' || buf[n - 1] == '\r' || buf[n - 1] == ' ' || buf[n - 1] == '\t')) buf[--n] = 0;
            if (buf[0]) return buf;
        }
    }
    return nullptr;
}

API int mt2_track_simple(const char* cal_path, unsigned long long pixel_ptr, int line_width_bytes, int width, int height, int nb,
                         const double* xyz_in, const unsigned char* good_in, double* xyz_out, int* idx_out, unsigned char* good_out,
                         char* status, int status_len, int flags) {
    if (!cal_path || !*cal_path) cal_path = mt2_cal_fallback();
    if (!cal_path) { mt2_status(status, status_len, "mt2_track_simple: no cal path (wire one, or set MT_GPU_CAL / mt_track_cal.txt)"); return -1; }
    if (!g_mt2_ctx || strcmp(cal_path, g_mt2_path) != 0) {
        if (g_mt2_ctx) { mt2_close(g_mt2_ctx); g_mt2_ctx = 0; }
        g_mt2_ctx = mt2_open(cal_path, 120, flags, status, status_len);
        if (!g_mt2_ctx) return -2;
        strncpy(g_mt2_path, cal_path, 1023); g_mt2_path[1023] = 0;
    }
    if (mt2_set_image(g_mt2_ctx, pixel_ptr, line_width_bytes, width, height) != 0) { mt2_status(status, status_len, "mt2_track_simple: bad image args"); return -3; }
    return mt2_track(g_mt2_ctx, nb, xyz_in, good_in, xyz_out, idx_out, good_out, status, status_len);
}

// The LabVIEW-facing entry (2026-09-09).  The tracking kernel's pane carries the bead-good flags as a BOOLEAN array, and no
// explicit Call Library parameter type can take one: the Numeric Type ring has no Boolean, and a Boolean-array wire into a
// U8-array parameter is a type mismatch that LabVIEW turns into a bad wire (measured, tools/bench/bool_wire_probe.log).
// So those two parameters are configured "Adapt to Type" / "Handles by Value" and arrive as LabVIEW array HANDLES; a Boolean
// array's data is one byte per element, so the handle's payload is exactly the uint8 buffer the rest of the code wants.
API int mt2_track_simple_b(const char* cal_path, unsigned long long pixel_ptr, int line_width_bytes, int width, int height, int nb,
                           const double* xyz_in, LvArrU8** good_in_h, double* xyz_out, int* idx_out, LvArrU8** good_out_h,
                           char* status, int status_len, int flags) {
    const unsigned char* gi = (good_in_h && *good_in_h) ? (*good_in_h)->d : nullptr;
    unsigned char* go = (good_out_h && *good_out_h) ? (*good_out_h)->d : nullptr;
    if (!go) { mt2_status(status, status_len, "mt2_track_simple_b: good_out handle is null"); return -4; }
    if (nb <= 0 && good_in_h && *good_in_h) nb = (*good_in_h)->n;          // the handle carries the length: no Array Size node needed
    return mt2_track_simple(cal_path, pixel_ptr, line_width_bytes, width, height, nb, xyz_in, gi, xyz_out, idx_out, go, status, status_len, flags);
}

// ============================================================================ v2 (gpuswap partB-dllv2-12, 2026-10-18) ==
// Calibration ARRAYS straight from LabVIEW's own `Array of cal clusters` + the two cosine windows, used AS GIVEN: no host DFT, no
// window build (the file route above recomputes cork / real / ampl from the raw stack - up to 6.75e-7 off LabVIEW's, lean_report_gpucal.md
// X1 - and builds its own windows).  Per bead, the cluster fields in LabVIEW's order:
//   forget I32 | z step DBL | cosband DBL[cb_len] | ampl DBL[rows][cols] | cork CDB[rows][cols] (re, im interleaved) | real DBL[rows][cols] | # slices I32
// dims[7 b ..] = {cb_len, ampl rows, ampl cols, cork rows, cork cols, real rows, real cols}; the bead arrays are concatenated in bead order.
// Any N (nb >= 1).  Every bead: rows == # slices == bead 0's # slices (the kernel has one S), cols == half - forget, cb_len >= 2 half - 1.
//   win_rs = 'Real-space cosine window' [cross], win_h = 'Cosine bandpass for Hilbert' [cross].
struct Mt2Host {
    int nb, cross, S; int* forget; double* zstep; int* nslices; int* dims; long long* off;     // off[4 b ..] = cosband, ampl, cork, real start (elements)
    double* cosband; double* ampl; double* cork; double* real; double* win_rs; double* win_h;
};
static void mt2_host_free(struct Mt2Host* H) {
    if (!H) return;
    free(H->forget); free(H->zstep); free(H->nslices); free(H->dims); free(H->off);
    free(H->cosband); free(H->ampl); free(H->cork); free(H->real); free(H->win_rs); free(H->win_h); free(H);
}
static void* mt2_dup(const void* p, size_t bytes) { void* q = malloc(bytes ? bytes : 1); if (q && bytes) memcpy(q, p, bytes); return q; }

API long long mt2_open_arrays(int nb, int cross, const int* forget, const double* zstep, const int* nslices, const int* dims,
                              const double* cosband, const double* ampl, const double* cork, const double* real,
                              const double* win_rs, const double* win_h, int flags, char* status, int status_len) {
    if (nb < 1 || cross <= 0 || cross > CROSS_MAX || !forget || !zstep || !nslices || !dims || !cosband || !ampl || !cork || !real || !win_rs || !win_h) {
        mt2_status(status, status_len, "mt2_open_arrays: bad arguments"); return 0;
    }
    if (g_mt2_live) { mt2_close(g_mt2_live); g_mt2_live = 0; }              // single-context policy, as mt2_open
    int half = (int)rint(cross / 2.0), n = 2 * half - 1, S = nslices[0];
    long long ncb = 0, na = 0, nc = 0, nr = 0;
    for (int b = 0; b < nb; b++) {
        const int* d = dims + 7 * b; int len = half - forget[b];
        if (forget[b] < 0 || len <= 0 || nslices[b] != S || d[1] != S || d[3] != S || d[5] != S || d[2] != len || d[4] != len || d[6] != len || d[0] < n) {
            snprintf(g_err, sizeof g_err, "mt2_open_arrays: bead %d cb %d ampl %dx%d cork %dx%d real %dx%d slices %d (S %d, half-forget %d, n %d)",
                     b, d[0], d[1], d[2], d[3], d[4], d[5], d[6], nslices[b], S, len, n);
            mt2_status(status, status_len, g_err); return 0;
        }
        ncb += d[0]; na += (long long)d[1] * d[2]; nc += (long long)d[3] * d[4]; nr += (long long)d[5] * d[6];
    }
    void* h = nullptr;
    if (mt_gpu_init(cross, S, nb, win_rs, win_h, &h) != 0) { mt2_status(status, status_len, g_err); return 0; }   // windows AS GIVEN
    struct Mt2Host* H = (struct Mt2Host*)calloc(1, sizeof(struct Mt2Host));
    H->nb = nb; H->cross = cross; H->S = S;
    H->forget = (int*)mt2_dup(forget, nb * sizeof(int)); H->zstep = (double*)mt2_dup(zstep, nb * sizeof(double));
    H->nslices = (int*)mt2_dup(nslices, nb * sizeof(int)); H->dims = (int*)mt2_dup(dims, 7 * nb * sizeof(int));
    H->cosband = (double*)mt2_dup(cosband, ncb * sizeof(double)); H->ampl = (double*)mt2_dup(ampl, na * sizeof(double));
    H->cork = (double*)mt2_dup(cork, 2 * nc * sizeof(double)); H->real = (double*)mt2_dup(real, nr * sizeof(double));
    H->win_rs = (double*)mt2_dup(win_rs, cross * sizeof(double)); H->win_h = (double*)mt2_dup(win_h, cross * sizeof(double));
    H->off = (long long*)calloc(4 * nb, sizeof(long long));
    long long ocb = 0, oa = 0, oc = 0, orr = 0; int rc = 0;
    for (int b = 0; b < nb && rc == 0; b++) {
        const int* d = dims + 7 * b; int len = d[2]; size_t nn = (size_t)S * len;
        H->off[4 * b] = ocb; H->off[4 * b + 1] = oa; H->off[4 * b + 2] = oc; H->off[4 * b + 3] = orr;
        double* cre = (double*)malloc(nn * sizeof(double)); double* cim = (double*)malloc(nn * sizeof(double));
        for (size_t i = 0; i < nn; i++) { memcpy(&cre[i], &cork[2 * (oc + i)], 8); memcpy(&cim[i], &cork[2 * (oc + i) + 1], 8); }   // bit copies
        rc = mt_gpu_set_bead(h, b, forget[b], zstep[b], cosband + ocb, nullptr, real + orr, ampl + oa, cre, cim, len);
        free(cre); free(cim);
        ocb += d[0]; oa += (long long)d[1] * d[2]; oc += (long long)d[3] * d[4]; orr += (long long)d[5] * d[6];
    }
    if (rc != 0) { mt2_status(status, status_len, g_err); mt2_host_free(H); mt_gpu_free(h); return 0; }
    Mt2* m = (Mt2*)calloc(1, sizeof(Mt2)); m->h = h; m->cross = cross; m->nb = nb; m->S = S; m->zstep = zstep[0]; m->keepalive = flags & 1; m->host = H;
    if (m->keepalive) mt_gpu_keepalive(1);
    snprintf(g_err, sizeof g_err, "No_Errors beads=%d slices=%d zstep=%.4g arrays", nb, S, zstep[0]); mt2_status(status, status_len, g_err);
    g_mt2_live = (long long)(intptr_t)m;
    return g_mt2_live;
}

// out[5] = nb, cross, half, S (the kernel's, one for all beads), n = 2 half - 1
API int mt2_get_dims(long long ctx, int* out) {
    Mt2* m = (Mt2*)(intptr_t)ctx; if (!m || !out) return -1;
    Ctx* c = (Ctx*)m->h; out[0] = m->nb; out[1] = c->cross; out[2] = c->half; out[3] = c->S; out[4] = 2 * c->half - 1; return 0;
}

// Read-back for the identity check.  field: 0 forget I32, 1 z step DBL, 2 # slices I32, 3 cosband, 4 ampl, 5 cork (re,im), 6 real,
// 7 win_rs, 8 win_h (bead ignored), 9 dims I32[7].  source 0 = the host copies the context holds, exactly as given (arrays route only;
// -3 on the file route); source 1 = the DEVICE buffers the kernel reads: cosband = n complex (the kernel's re = given, im = 0),
// ampl / real = S x half DBL and cork = S x half complex in the kernel's padded layout (cols < forget zero-filled), # slices = the kernel's S.
// Returns the byte count of the field (writes it when out_bytes >= that count), negative on error.
API long long mt2_get_cal(long long ctx, int bead, int field, int source, void* out, long long out_bytes) {
    Mt2* m = (Mt2*)(intptr_t)ctx; if (!m) return -1;
    Ctx* c = (Ctx*)m->h; int half = c->half, n = 2 * half - 1, S = c->S;
    if (field != 7 && field != 8 && (bead < 0 || bead >= m->nb)) return -2;
    long long bytes = 0;
    if (source == 0) {
        struct Mt2Host* H = m->host; if (!H) return -3;
        const long long* o = H->off + 4 * bead; const int* d = H->dims + 7 * bead; const void* src = nullptr;
        switch (field) {
        case 0: src = &H->forget[bead]; bytes = 4; break;
        case 1: src = &H->zstep[bead]; bytes = 8; break;
        case 2: src = &H->nslices[bead]; bytes = 4; break;
        case 3: src = H->cosband + o[0]; bytes = 8LL * d[0]; break;
        case 4: src = H->ampl + o[1]; bytes = 8LL * d[1] * d[2]; break;
        case 5: src = H->cork + 2 * o[2]; bytes = 16LL * d[3] * d[4]; break;
        case 6: src = H->real + o[3]; bytes = 8LL * d[5] * d[6]; break;
        case 7: src = H->win_rs; bytes = 8LL * H->cross; break;
        case 8: src = H->win_h; bytes = 8LL * H->cross; break;
        case 9: src = d; bytes = 28; break;
        default: return -4;
        }
        if (out && out_bytes >= bytes) memcpy(out, src, (size_t)bytes);
        return bytes;
    }
    if (source != 1) return -4;
    const void* dev = nullptr;
    switch (field) {
    case 0: dev = c->d_forget + bead; bytes = 4; break;
    case 1: dev = c->d_zstep + bead; bytes = 8; break;
    case 2: if (out && out_bytes >= 4) memcpy(out, &c->S, 4); return 4;
    case 3: dev = c->d_cosband + (size_t)bead * n; bytes = 16LL * n; break;
    case 4: dev = c->d_ampl + (size_t)bead * S * half; bytes = 8LL * S * half; break;
    case 5: dev = c->d_cork + (size_t)bead * S * half; bytes = 16LL * S * half; break;
    case 6: dev = c->d_real + (size_t)bead * S * half; bytes = 8LL * S * half; break;
    case 7: dev = c->d_win_rs; bytes = 8LL * c->cross; break;
    case 8: dev = c->d_win_h; bytes = 8LL * c->cross; break;
    default: return -4;
    }
    if (out && out_bytes >= bytes && cudaMemcpy(out, dev, (size_t)bytes, cudaMemcpyDeviceToHost) != cudaSuccess) { cudaGetLastError(); return -5; }
    return bytes;
}
