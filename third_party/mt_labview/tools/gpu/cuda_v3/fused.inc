// fused.inc v3 (gpuswap dllv3-14, 2026-10-19; cuda_v3/ copy of cuda_v2/fused.inc b89d7b97): D1 D2 D4 D5 D6 D7 of diag13
// cpu_rules_edge_low.md section 3, + variants D8 (CPU_SGL_PREP) / D9 (CPU_SGL_CENTRE), default off. Every change is marked `v3 Dn`.
// fused.inc - ONE kernel per frame (2026-09-08, user's direction: "cpu<->gpu 통신 최소화" - one launch instead of ~25 API calls).
// One thread block per bead (256 threads) runs the whole per-bead pipeline in shared memory with in-kernel DFTs:
//   cross profiles -> prep -> DFT(120) -> window+square -> 3 x { IDFT(120) -> |.| rotated -> argmax -> parabola -> phase shift }
//   -> radial profile (bilinear binning, SGL) -> mirrored 119 -> DFT(119) -> cosine band -> IDFT(119) -> corkscrew
//   -> SSD fit vs calibration slices -> weighted phases -> quadratic fit [2,4,5,4,2] -> z ; bounds -> good.
// The formulas are those of the separate kernels in mt_track.cu (same order, same SGL roundings); only the FFT is a two-stage
// (n1 x n2 Cooley-Tukey) double-precision DFT in shared memory (cuFFT-equivalent to ~1e-13; the inverse is unnormalised like cuFFT, the /n happens where it did).
// cuFFTDx was evaluated (MathDx 25.6 needs CUDA >= 12.8, preliminary MSVC support, no double size 119/120 on sm_75) - not used.

#define FUSED_THREADS 256
#define NMIR_MAX (CROSS_MAX - 1)

// twiddle tables: tw[m] = exp(-2 pi i m / n) for m in [0, n)
__device__ __forceinline__ void build_twiddles(int n, double* re, double* im) {
    for (int m = threadIdx.x; m < n; m += blockDim.x) { double s, c; sincospi(-2.0 * m / n, &s, &c); re[m] = c; im[m] = s; }
}
// out[k] = sum_t in[t] * tw[(k*t) mod n]  (sign = +1: forward with tw = exp(-i..); sign = -1 uses conj(tw) = inverse, unnormalised)
__device__ __forceinline__ double2 dft_bin(const double2* in, int n, int k, const double* twre, const double* twim, int sign) {
    double sr = 0, si = 0; int m = 0;
    for (int t = 0; t < n; t++) {
        double cr = twre[m], ci = sign > 0 ? twim[m] : -twim[m]; double2 v = in[t];
        sr += v.x * cr - v.y * ci; si += v.x * ci + v.y * cr;
        m += k; if (m >= n) m -= n;
    }
    return make_double2(sr, si);
}


// Two-stage (Cooley-Tukey, n = n1*n2) block-cooperative DFT: X[k1 + n1 k2] = sum_t2 W^(n1 t2 k2) [ W^(t2 k1) sum_t1 x[n2 t1 + t2] W^(n2 t1 k1) ]
// with W = exp(-2 pi i / n) (sign > 0) or its conjugate (inverse, unnormalised). n (n1 + n2) MACs instead of n^2: 120 = 8 x 15 -> 2760,
// 119 = 7 x 17 -> 2856 (vs 14400 / 14161). ALL threads of the block must call it (internal __syncthreads); a thread works if j < n.
__device__ __forceinline__ void dft2(const double2* in, double2* stage, double2* out, int n, int n1, int n2, int j,
                                     const double* twre, const double* twim, int sign) {
    if (j < n) {
        int t2 = j / n1, k1 = j - t2 * n1; double sr = 0, si = 0; int m = 0, step = (n2 * k1) % n;
        for (int t1 = 0; t1 < n1; t1++) {
            double2 v = in[n2 * t1 + t2]; double cr = twre[m], ci = sign > 0 ? twim[m] : -twim[m];
            sr += v.x * cr - v.y * ci; si += v.x * ci + v.y * cr; m += step; if (m >= n) m -= n;
        }
        int mt = (t2 * k1) % n; double cr = twre[mt], ci = sign > 0 ? twim[mt] : -twim[mt];
        stage[j] = make_double2(sr * cr - si * ci, sr * ci + si * cr);
    }
    __syncthreads();
    if (j < n) {
        int k1 = j % n1, k2 = j / n1; double sr = 0, si = 0; int m = 0, step = (n1 * k2) % n;
        for (int t2 = 0; t2 < n2; t2++) {
            double2 v = stage[t2 * n1 + k1]; double cr = twre[m], ci = sign > 0 ? twim[m] : -twim[m];
            sr += v.x * cr - v.y * ci; si += v.x * ci + v.y * cr; m += step; if (m >= n) m -= n;
        }
        out[j] = make_double2(sr, si);
    }
    __syncthreads();
}
__device__ __forceinline__ void factor2(int n, int* n1, int* n2) {          // smallest factor >= 2 ... prefer balanced: n1 = largest divisor <= sqrt(n)
    int best = 1; for (int d = 2; d * d <= n; d++) if (n % d == 0) best = d;
    *n1 = best; *n2 = n / best;                                              // 120 -> 10 x 12 ; 119 -> 7 x 17 ; prime n -> 1 x n (= direct DFT)
}

__global__ void __launch_bounds__(FUSED_THREADS) k_fused(const unsigned char* img, int H, int W, const int* xin, const int* yin, const int* goodin,
                        int cross, int half, int h, int arm, int n_end, const double* win_rs, const double* win_h,
                        const int* forget, const double* zstep, const double* real, const double* ampl, const cufftDoubleComplex* cork,
                        const cufftDoubleComplex* cosband, int S, double z_lo, double z_hi_margin, double xy_lo, double xy_hi,
                        double* xout, double* yout, double* zout, int* idxout, int* goodout) {
    const int bead = blockIdx.x, t = threadIdx.x; const int n = 2 * half - 1;
    __shared__ double s_twre[2][CROSS_MAX / 2], s_twim[2][CROSS_MAX / 2], s_tw2re[NMIR_MAX], s_tw2im[NMIR_MAX];   // v3 D6: per-axis twiddles of length n (128 threads per axis -> cross <= 128)
    __shared__ double2 s_spec[2][CROSS_MAX];            // per-axis spectrum (in place through the rounds)
    __shared__ double2 s_tmp[2][CROSS_MAX];             // per-axis inverse transform / profile scratch
    __shared__ double s_c[2][CROSS_MAX];                // |rotated inverse| / cross
    __shared__ double s_base[2], s_d[2], s_P[2], s_r1[2];
    __shared__ int s_arg[2];
    __shared__ double s_s[CROSS_MAX / 2 + 1], s_w[CROSS_MAX / 2 + 1], s_rad[CROSS_MAX / 2];
    __shared__ double2 s_mir[NMIR_MAX], s_mirf[NMIR_MAX];
    __shared__ double2 s_stage[2][CROSS_MAX];            // dft2 intermediate (per axis; [0] reused for the 119-point transforms)
    __shared__ double s_re[CROSS_MAX / 2], s_im[CROSS_MAX / 2], s_abs[CROSS_MAX / 2];
    __shared__ double s_ssd[256]; __shared__ int s_idx; __shared__ double s_ph[NPTS], s_num[NPTS][32], s_den[NPTS][32];

    if (!goodin[bead]) { if (t == 0) { xout[bead] = -1; yout[bead] = -1; zout[bead] = -1; idxout[bead] = -1; goodout[bead] = 0; } return; }
    const int axis = t >> 7, j = t & 127;                 // threads 0..127 -> axis 0 (x, along-x profile), 128..255 -> axis 1
    // v3 D5 (diag13 cpu_rules_edge_low.md section 3 A): the CPU's CLIPPED sub-image (rect coord from center + IMAQ ImageToArray):
    // origin (max(0, x-h), max(0, y-h)), size (min(W, x+h) - ox, min(H, y+h) - oy); the cross centre stays (h, h) in SUB coordinates.
    // 2D Array Subset: start < 0 -> 0 with the length kept, truncated at the sub end.  Every image read below stays inside the sub;
    // an interior pick (window inside the image) reads exactly the v2 pixels.
    const int ox = max(0, xin[bead] - h), oy = max(0, yin[bead] - h);
    const int sw = max(0, min(W, xin[bead] + h) - ox), sh = max(0, min(H, yin[bead] + h) - oy);
    const int arm2 = (int)lv_rint(arm / 2.0), pc0 = max(0, h - half), ar0 = max(0, h - arm2);
    const int nX = max(0, min(cross, sw - pc0)), nY = max(0, min(cross, sh - pc0));     // v3 D6: profile length n along x / along y
    const int nA = (axis == 0) ? nX : nY;
    for (int m = j; m < nA; m += 128) { double s, c; sincospi(-2.0 * m / nA, &s, &c); s_twre[axis][m] = c; s_twim[axis][m] = s; }   // = build_twiddles(n)
    build_twiddles(n, s_tw2re, s_tw2im);
    int c1, c2, m1, m2; factor2(nA, &c1, &c2); factor2(n, &m1, &m2);
    // ---- A. cross profiles (SGL sum / SGL arm) over the rows / cols that exist (v3 D5), stored as the real part of s_tmp[axis]
    if (j < nA) {
        float sum = 0.f;
        if (axis == 0) { int col = ox + pc0 + j; for (int i = 0; i < arm; i++) if (ar0 + i < sh) sum += (float)img[(size_t)(oy + ar0 + i) * W + col]; }
        else           { int row = oy + pc0 + j; for (int i = 0; i < arm; i++) if (ar0 + i < sw) sum += (float)img[(size_t)row * W + (ox + ar0 + i)]; }
        s_tmp[axis][j] = make_double2((double)(sum / (float)arm), 0.0);
    }
    __syncthreads();
#ifndef CPU_SGL_PREP
    if (j == 0) {                                          // base = (sum_{i<n_end} p[i] + sum_{i<n_end} p[cross-i]) / (2 n_end); v3 D6: p[q] = 0 for q >= n
        double acc = 0; for (int i = 0; i < n_end; i++) { if (i < nA) acc += s_tmp[axis][i].x; int q = cross - i; if (q < nA) acc += s_tmp[axis][q].x; }
        s_base[axis] = acc / (2.0 * n_end);
    }
    __syncthreads();
    if (j < nA) s_tmp[axis][j] = make_double2((s_tmp[axis][j].x - s_base[axis]) * win_rs[j], 0.0);
#else
    // v3 D8 variant (CPU_SGL_PREP; diag13 section 3 D8): the CPU prep VI's SGL terminals - SGL sum of p[0..n_end-1] then of p[cross-i]
    // (i = 0..n_end-1, Index Array out of range -> 0), base = SGL(sum / SGL(2 n_end)), out = SGL(SGL(p - base) * SGL(window)).
    if (j == 0) {
        float acc = 0.f;
        for (int i = 0; i < n_end; i++) acc = __fadd_rn(acc, (i < nA) ? (float)s_tmp[axis][i].x : 0.f);
        for (int i = 0; i < n_end; i++) { int q = cross - i; acc = __fadd_rn(acc, (q < nA) ? (float)s_tmp[axis][q].x : 0.f); }
        s_base[axis] = (double)__fdiv_rn(acc, (float)(2 * n_end));
    }
    __syncthreads();
    if (j < nA) { float d = __fsub_rn((float)s_tmp[axis][j].x, (float)s_base[axis]); s_tmp[axis][j] = make_double2((double)__fmul_rn(d, (float)win_rs[j]), 0.0); }
#endif
    __syncthreads();
    // ---- B. forward DFT, window, square
    dft2(s_tmp[axis], s_stage[axis], s_spec[axis], nA, c1, c2, j, s_twre[axis], s_twim[axis], +1);   // v3 D6: over n
    if (j < nA) { double2 F = s_spec[axis][j]; F.x *= win_h[j]; F.y *= win_h[j]; s_spec[axis][j] = make_double2(F.x * F.x - F.y * F.y, 2.0 * F.x * F.y); }
    __syncthreads();
    // ---- C. three rounds: inverse DFT -> |rotated|/cross -> argmax -> parabola -> phase shift
    for (int round = 0; round < 3; round++) {
        dft2(s_spec[axis], s_stage[axis], s_tmp[axis], nA, c1, c2, j, s_twre[axis], s_twim[axis], -1);
        if (j < nA) { int src = (j - half) % nA; if (src < 0) src += nA; double2 v = s_tmp[axis][src]; s_c[axis][j] = sqrt(v.x * v.x + v.y * v.y) / nA; }   // v3 D6: rotate by half mod n, / n
        __syncthreads();
        if (j == 0) {
            int bi = 0; double best = s_c[axis][0];
            for (int i = 1; i < nA; i++) if (s_c[axis][i] > best) { best = s_c[axis][i]; bi = i; }   // first maximum
            int lo = bi - NPTS / 2; double xs[NPTS], ys[NPTS];
            for (int i = 0; i < NPTS; i++) { int q = lo + i; xs[i] = (double)q; ys[i] = (q >= 0 && q < nA) ? s_c[axis][q] : 0.0; }
            double a2, a1, a0; quadfit3(xs, ys, nullptr, &a2, &a1, &a0);
            double Pk = -(a1 / a2) / 2.0, d;
            if (round == 0) { double r1 = lv_rint(Pk); s_r1[axis] = r1; s_P[axis] = Pk; d = Pk - r1; }
            else { double out = Pk - s_r1[axis]; s_P[axis] += out; d = out; }
            s_d[axis] = d; s_arg[axis] = bi;
        }
        __syncthreads();
        if (round < 2 && j < nA) {                         // v3 D6: ramp constant 2 half (#566), not n
            double a = (j > half) ? (double)(j - 2 * half) : (double)j; double th = 2.0 * M_PI / (2 * half) * s_d[axis] * a;
            double2 Sp = s_spec[axis][j]; double c = cos(th), s = sin(th);
            s_spec[axis][j] = make_double2(Sp.x * c - Sp.y * s, Sp.x * s + Sp.y * c);
        }
        __syncthreads();
    }
    // ---- D. radial profile around (h + shift): bilinear binning with shared atomics, SGL result, mirrored 119
    // v3 D6: a profile shorter than the 5-point parabola gives no centre (offline center(): NaN -> x / y NaN -> pos -1, good F)
    double shx = (nX < NPTS) ? nan("") : (s_P[0] - half) / 2.0, shy = (nY < NPTS) ? nan("") : (s_P[1] - half) / 2.0;
    if (t == 0) { xout[bead] = xin[bead] + shx; yout[bead] = yin[bead] + shy; }
    if (t <= half) { s_s[t] = 0; s_w[t] = 0; }
    __syncthreads();
    if (isfinite(shx) && isfinite(shy)) {                  // v3: no centre -> no image read (pos -1 / good F follow from x / y)
#ifndef CPU_SGL_CENTRE
        double xc = h + shx, yc = h + shy;
#else
        double xc = (double)(float)(h + shx), yc = (double)(float)(h + shy);   // v3 D9 variant (CPU_SGL_CENTRE): the radial VI's SGL x / y centre controls
#endif
        int wx0 = (int)ceil(xc) - half, wy0 = (int)ceil(yc) - half; double cx = half + (xc - ceil(xc)), cy = half + (yc - ceil(yc));
        // v3 D7: the window is a 2D Array Subset of the CLIPPED sub - start < 0 -> 0 (length kept), rows / cols past the sub absent;
        // j outside the row -> p = 0 but the weights are still added (v2's `continue` skipped both, also at j = cross in interior windows)
        const int wxs = max(0, wx0), wys = max(0, wy0), wnc = max(0, min(cross, sw - wxs)), wnr = max(0, min(cross, sh - wys));
        for (int i = t; i < wnr; i += blockDim.x) {
            double dy = cy - i, dy2 = dy * dy, c = sqrt((double)half * half - dy2);
            int N = (int)ceil(2 * c), j0 = (int)ceil(cx - c);
            for (int kk = 0; kk < N; kk++) {
                int jj = j0 + kk;
                double p = (jj >= 0 && jj < wnc) ? (double)img[(size_t)(oy + wys + i) * W + (ox + wxs + jj)] : 0.0;   // v3 D7: outside the row p = 0, weights added
                double dx = cx - jj, r = sqrt(dx * dx + dy2), rf = floor(r), fr = r - rf; int ri = (int)rf;
                if (ri < half) { atomicAdd(&s_s[ri], (1 - fr) * p); atomicAdd(&s_w[ri], 1 - fr); }
                if (ri + 1 < half) { atomicAdd(&s_s[ri + 1], fr * p); atomicAdd(&s_w[ri + 1], fr); }
            }
        }
    }
    __syncthreads();
    if (t < half) { float v = (float)(s_s[t] / s_w[t]); s_rad[t] = (double)v; }
    __syncthreads();
    for (int q = t; q < n; q += blockDim.x) { int r = (q >= half - 1) ? (q - (half - 1)) : (half - 1 - q); s_mir[q] = make_double2(s_rad[r], 0.0); }
    __syncthreads();
    // ---- E. DFT(119) -> cosine band -> IDFT(119): corkscrew = out[half-1+r] / n for r >= forget
    dft2(s_mir, s_stage[0], s_mirf, n, m1, m2, t, s_tw2re, s_tw2im, +1);
    if (t < n) { double2 F = s_mirf[t]; cufftDoubleComplex cb = cosband[bead * n + t]; s_mirf[t] = make_double2(F.x * cb.x - F.y * cb.y, F.x * cb.y + F.y * cb.x); }
    __syncthreads();
    dft2(s_mirf, s_stage[0], s_mir, n, m1, m2, t, s_tw2re, s_tw2im, -1);           // inverse back into s_mir (unnormalised)
    const int f = forget[bead];
    if (t < half) {
        if (t >= f) { double2 v = s_mir[half - 1 + t]; s_re[t] = v.x / n; s_im[t] = v.y / n; }
        else { s_re[t] = 0; s_im[t] = 0; }
        s_abs[t] = sqrt(s_re[t] * s_re[t] + s_im[t] * s_im[t]);
    }
    __syncthreads();
    // ---- F. SSD fit to the calibration stack, phases, quadratic fit, z, bounds  (identical to k_z)
    for (int s = t; s < S; s += blockDim.x) {
        double acc = 0; const double* row = real + ((size_t)bead * S + s) * half;
        for (int r = f; r < half; r++) { double d = s_re[r] - row[r]; acc += d * d; }
        s_ssd[s] = acc;
    }
    __syncthreads();
    if (t == 0) {
        int bi = 0; for (int s = 1; s < S; s++) if (s_ssd[s] < s_ssd[bi]) bi = s;   // positive argmin: unchanged from v1
        // v2 (gpuswap partB-dllv2-12; cpu_rules_v2.md section 2(i), PINNED): pos = -1 iff x or y non-finite OR the squared-difference
        // array has no finite element (= the pick's calibration stack non-finite).  The positive value rule (2(ii)) is NOT pinned.
        int anyfin = 0; for (int s = 0; s < S; s++) if (isfinite(s_ssd[s])) { anyfin = 1; break; }
        if (!isfinite(xout[bead]) || !isfinite(yout[bead]) || !anyfin) bi = -1;
        s_idx = bi;
    }
    __syncthreads();
    const int idx = s_idx; const int lane = t & 31, wid = t >> 5;
    if (wid < NPTS) {
        int s0 = (idx - 2 < 0) ? 0 : idx - 2; int s = s0 + wid; /* v3 D1 */ double num = 0, den = 0;
        if (s >= 0 && s < S) {
            const double* arow = ampl + ((size_t)bead * S + s) * half; const cufftDoubleComplex* crow = cork + ((size_t)bead * S + s) * half;
            for (int r = f + lane; r < half; r += 32) {
                double w = s_abs[r] * arow[r];
                double re = s_re[r] * crow[r].x + s_im[r] * crow[r].y, im = s_im[r] * crow[r].x - s_re[r] * crow[r].y;
                num += w * atan2(im, re); den += w;
            }
        }
        s_num[wid][lane] = num; s_den[wid][lane] = den;
    }
    __syncthreads();
    if (t < NPTS) { double num = 0, den = 0; for (int l = 0; l < 32; l++) { num += s_num[t][l]; den += s_den[t][l]; } s_ph[t] = num / den; }
    __syncthreads();
    if (t == 0) {
        double zi;
        if (idx < 0) zi = -1.0;                                                        // v2, section 2(i): pos -1 -> zi = -1 exactly, Z = -1 x z step
        else if (idx + 2 >= S /* v3 D2 */) zi = (double)idx;
        else { const double W5[NPTS] = {(double)0.4f, (double)0.8f, 1.0, (double)0.8f, (double)0.4f} /* v3 D4 */; double ys[NPTS], a2, a1, a0; for (int i = 0; i < NPTS; i++) ys[i] = (double)(i - NPTS / 2); quadfit3(s_ph, ys, W5, &a2, &a1, &a0); zi = idx + a0; }
        zout[bead] = zi * zstep[bead]; idxout[bead] = idx;
        double x = xout[bead], y = yout[bead];
        // v2 good rule (cpu_rules_v2.md section 1, PINNED): good_in AND X > 10 AND X < 1280 AND Y > 10 AND Y < 1024 AND zi > 1 AND
        // zi < S - 2, strict DBL compares (a NaN operand gives FALSE).  good_in FALSE never gets here (the constants at the kernel top).
        // The v1 terms (z_lo / z_hi_margin / xy_lo / xy_hi, the 72-px edge) are no longer used by this kernel.
        int good = (x > 10.0) && (x < 1280.0) && (y > 10.0) && (y < 1024.0) && (zi > 1.0) && (zi < (double)(S - 2));
        goodout[bead] = good ? 1 : 0;
    }
}

// host side: same Ctx buffers, one launch + the same memcpys as mt_gpu_track (image up, 3 small ups, 5 small downs)
// mt_gpu_track_fused_dev: the image is ALREADY in c->d_img (mt2 uploads it with cudaMemcpy2D from the IMAQ buffer)
API int mt_gpu_track_fused_dev(void* handle, int H, int W, int nb, const int* x_in, const int* y_in, const int* good_in,
                               double* x_out, double* y_out, double* z_out, int* idx_out, int* good_out) {
    Ctx* c = (Ctx*)handle;
    if (nb > c->nb_alloc) { snprintf(g_err, sizeof g_err, "track_fused: nb %d > nb_alloc %d", nb, c->nb_alloc); return -1; }
    c->H = H; c->W = W; c->nb = nb;
    LARGE_INTEGER qf, q1, q2, q3; QueryPerformanceFrequency(&qf); QueryPerformanceCounter(&q1);
    CK(cudaMemcpy(c->d_xin, x_in, nb * sizeof(int), cudaMemcpyHostToDevice)); CK(cudaMemcpy(c->d_yin, y_in, nb * sizeof(int), cudaMemcpyHostToDevice));
    CK(cudaMemcpy(c->d_goodin, good_in, nb * sizeof(int), cudaMemcpyHostToDevice));
    static cudaEvent_t fe0 = nullptr, fe1 = nullptr; if (!fe0) { cudaEventCreate(&fe0); cudaEventCreate(&fe1); } cudaEventRecord(fe0, 0);
    k_fused<<<nb, FUSED_THREADS>>>(c->d_img, H, W, c->d_xin, c->d_yin, c->d_goodin, c->cross, c->half, c->h, c->arm, c->n_end, c->d_win_rs, c->d_win_h,
                                   c->d_forget, c->d_zstep, c->d_real, c->d_ampl, c->d_cork, c->d_cosband, c->S, c->z_lo, c->z_hi_margin, c->xy_lo, c->xy_hi,
                                   c->d_xout, c->d_yout, c->d_zout, c->d_idx, c->d_goodout);
    CK(cudaGetLastError());
    cudaEventRecord(fe1, 0); CK(cudaStreamSynchronize(0)); QueryPerformanceCounter(&q2); { float ms = 0; cudaEventElapsedTime(&ms, fe0, fe1); g_t_ev = ms; }
    CK(cudaMemcpy(x_out, c->d_xout, nb * sizeof(double), cudaMemcpyDeviceToHost)); CK(cudaMemcpy(y_out, c->d_yout, nb * sizeof(double), cudaMemcpyDeviceToHost));
    CK(cudaMemcpy(z_out, c->d_zout, nb * sizeof(double), cudaMemcpyDeviceToHost)); CK(cudaMemcpy(idx_out, c->d_idx, nb * sizeof(int), cudaMemcpyDeviceToHost));
    CK(cudaMemcpy(good_out, c->d_goodout, nb * sizeof(int), cudaMemcpyDeviceToHost));
    QueryPerformanceCounter(&q3); g_t_gpu = 1e3 * (double)(q2.QuadPart - q1.QuadPart) / qf.QuadPart; g_t_dn = 1e3 * (double)(q3.QuadPart - q2.QuadPart) / qf.QuadPart;
    return 0;
}

API int mt_gpu_track_fused(void* handle, const unsigned char* image, int H, int W, int nb, const int* x_in, const int* y_in, const int* good_in,
                           double* x_out, double* y_out, double* z_out, int* idx_out, int* good_out) {
    Ctx* c = (Ctx*)handle; size_t bytes = (size_t)H * W;
    if (bytes != c->img_bytes) { if (c->d_img) cudaFree(c->d_img); CK(cudaMalloc(&c->d_img, bytes)); c->img_bytes = bytes; }
    LARGE_INTEGER qf, q0, q1; QueryPerformanceFrequency(&qf); QueryPerformanceCounter(&q0);
    CK(cudaMemcpy(c->d_img, image, bytes, cudaMemcpyHostToDevice));
    QueryPerformanceCounter(&q1); g_t_up = 1e3 * (double)(q1.QuadPart - q0.QuadPart) / qf.QuadPart;
    return mt_gpu_track_fused_dev(handle, H, W, nb, x_in, y_in, good_in, x_out, y_out, z_out, idx_out, good_out);
}

static int g_fused = 1;                                   // default: the fused kernel; mt_gpu_set_fused(0) selects the 25-call path (A/B)
API int mt_gpu_set_fused(int on) { g_fused = on ? 1 : 0; return g_fused; }
API int mt_gpu_track_any(void* handle, const unsigned char* image, int H, int W, int nb, const int* x_in, const int* y_in, const int* good_in,
                         double* x_out, double* y_out, double* z_out, int* idx_out, int* good_out) {
    return g_fused ? mt_gpu_track_fused(handle, image, H, W, nb, x_in, y_in, good_in, x_out, y_out, z_out, idx_out, good_out)
                   : mt_gpu_track(handle, image, H, W, nb, x_in, y_in, good_in, x_out, y_out, z_out, idx_out, good_out);
}

// ---- GPU clock keep-alive v2 (2026-09-09): the RTX 2060 sits in P8 (300-360 MHz) when ~1 ms of GPU work arrives every ~15 ms
// and every phase then runs ~3.8x slower (1365/360). The NVIDIA "prefer maximum performance" profile only governs apps with a
// 3D context (LabVIEW has none; measured: still P8), locking clocks needs admin. An infinite spin kernel stalled the work
// stream under WDDM (v1). v2: a DLL host thread launches a SHORT dummy kernel (~0.3 ms) every ~1.5 ms on a side stream, so
// utilisation stays high enough for the governor while every kernel completes. Opt-in via MT_GPU_KEEPALIVE=1 or mt_gpu_keepalive(1).
__global__ void k_busy(double* sink, int iters) {
    double x = 1.0 + threadIdx.x * 1e-9; for (int i = 0; i < iters; i++) x = x * 1.0000001 + 1e-9;
    if (x == 12345.0) sink[threadIdx.x] = x;                       // never true; keeps the loop alive
}
static cudaStream_t g_keep_stream = nullptr; static double* g_keep_sink = nullptr; static volatile int g_keep_on = 0; static HANDLE g_keep_thread = nullptr;
static int g_keep_iters = 2000, g_keep_period_ms = 1;
static unsigned char* g_keep_buf = nullptr; static size_t g_keep_bytes = 256u << 20; static size_t g_keep_copy = 64u << 20;   // 64 MB / ms: keeps the memory clock at P2 (measured 2026-09-09), +7 W
// Idle timeout (2026-09-09, user: the experiment VI is usually stopped with LabVIEW's Abort button, so mt2_close never runs).
// The thread parks itself when no track call has arrived for g_keep_idle_ms and wakes on the next one, so an aborted run cannot
// leave the GPU busy-looped forever.  mt_gpu_keepalive_touch() is called at the top of every track entry point.
static volatile LONGLONG g_keep_last_use = 0; static int g_keep_idle_ms = 2000;
static LONGLONG qpc_now() { LARGE_INTEGER t; QueryPerformanceCounter(&t); return t.QuadPart; }
static double qpc_ms(LONGLONG a, LONGLONG b) { LARGE_INTEGER f; QueryPerformanceFrequency(&f); return 1e3 * (double)(b - a) / (double)f.QuadPart; }
API void mt_gpu_keepalive_touch() { g_keep_last_use = qpc_now(); }
static DWORD WINAPI keep_thread(LPVOID) {
    while (g_keep_on) {                                                   // v3: MEMORY traffic (the memory clock is what drops: 6801 -> 405 MHz)
        if (g_keep_idle_ms > 0 && g_keep_last_use && qpc_ms(g_keep_last_use, qpc_now()) > g_keep_idle_ms) { Sleep(50); continue; }   // parked: no tracking for a while (VI aborted)
        cudaMemcpyAsync(g_keep_buf + g_keep_bytes / 2, g_keep_buf, g_keep_copy, cudaMemcpyDeviceToDevice, g_keep_stream);
        k_busy<<<30, 128, 0, g_keep_stream>>>(g_keep_sink, g_keep_iters);
        cudaStreamSynchronize(g_keep_stream);
        if (g_keep_period_ms > 0) Sleep(g_keep_period_ms);
    }
    return 0;
}
API int mt_gpu_keepalive(int on) {
    if (on && !g_keep_on) {
        if (!g_keep_stream) { CK(cudaStreamCreateWithFlags(&g_keep_stream, cudaStreamNonBlocking)); CK(cudaMalloc(&g_keep_sink, 256 * sizeof(double))); CK(cudaMalloc(&g_keep_buf, g_keep_bytes)); }
        mt_gpu_keepalive_touch();                                          // start un-parked
        g_keep_on = 1; g_keep_thread = CreateThread(nullptr, 0, keep_thread, nullptr, 0, nullptr);
    } else if (!on && g_keep_on) {
        g_keep_on = 0; if (g_keep_thread) { WaitForSingleObject(g_keep_thread, 2000); CloseHandle(g_keep_thread); g_keep_thread = nullptr; }
    }
    return g_keep_on;
}
API int mt_gpu_keepalive_tune(int iters, int period_ms, int copy_mb) { g_keep_iters = iters; g_keep_period_ms = period_ms; if (copy_mb > 0 && (size_t)copy_mb << 20 <= g_keep_bytes / 2) g_keep_copy = (size_t)copy_mb << 20; return 0; }
API int mt_gpu_keepalive_idle(int idle_ms) { g_keep_idle_ms = idle_ms; return g_keep_idle_ms; }   // 0 = never park (old behaviour)
API int mt_gpu_keepalive_state() { return g_keep_on ? (g_keep_idle_ms > 0 && g_keep_last_use && qpc_ms(g_keep_last_use, qpc_now()) > g_keep_idle_ms ? 2 : 1) : 0; }   // 0 off, 1 running, 2 parked
