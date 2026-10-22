// mt_track.cu - CUDA implementation of the magnetic-tweezers bead-tracking kernel
// `Track 1 of N bds xyz-kernel-reentrant.vi` (KimLab MT room, UNIST), one step per analysis subVI, batched over beads.
// Semantics: tools/gpu/ref_numpy.py (verified against the LabVIEW kernel on the recorded fixture, 2026-09-07) — the VI's
// computation is reproduced step by step (rule 1a); only the executor changes.  Reading aid: the UCSB Saleh-lab
// C/CUDA port (Tabrizi/Lansdorp/Saleh 2013, BSD) — ABI style only, no code copied.
//
// C API (LabVIEW Call Library Function Node, cdecl, all arrays as data pointers):
//   mt_gpu_init(cross, n_slices, half_len, win_rs[cross], win_h[cross], &handle)
//   mt_gpu_set_bead(handle, b, forget, zstep, cosband_re/im[>=2*half-1], real[S*len], ampl[S*len], cork_re/im[S*len], len)
//   mt_gpu_set_bounds(handle, z_lo, z_hi_margin, xy_lo, xy_hi)              (the kernel's "Bead is good?" constants)
//   mt_gpu_track(handle, image_u8[H*W], H, W, nb, x_in[nb], y_in[nb], good_in[nb], x_out, y_out, z_out, idx_out, good_out)
//   mt_gpu_free(handle); mt_gpu_last_error()
// Build: nvcc -O2 -arch=sm_75 -Xcompiler "/MD" -shared -o mt_track.dll mt_track.cu -lcufft
#define NOMINMAX
#include <windows.h>
#include <cuda_runtime.h>
#include <cufft.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

#define API extern "C" __declspec(dllexport)
#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif
#define CROSS_MAX 256
#define NPTS 5

static char g_err[512] = "";
static double g_t_up = 0, g_t_gpu = 0, g_t_dn = 0, g_t_ev = 0;   // + GPU-timeline ms from cudaEvents around the kernel section   // ms: host->device upload | kernels+FFTs (to sync) | device->host readback (last call)
static void set_err(const char* what, cudaError_t e) { snprintf(g_err, sizeof g_err, "%s: %s", what, cudaGetErrorString(e)); }
#define CK(call) do { cudaError_t _e = (call); if (_e != cudaSuccess) { set_err(#call, _e); return -1; } } while (0)
#define CKF(call) do { cufftResult _r = (call); if (_r != CUFFT_SUCCESS) { snprintf(g_err, sizeof g_err, "%s: cufft %d", #call, (int)_r); return -1; } } while (0)

struct Ctx {
    int cross, half, h, arm, n_end, S, nb_alloc, nb;
    double k_half;
    // per bead calibration (padded to width `half`, column r holds the VI's column r - forget)
    int* d_forget; double* d_zstep; cufftDoubleComplex* d_cosband; double* d_real; double* d_ampl; cufftDoubleComplex* d_cork;
    double* d_win_rs; double* d_win_h;
    // bounds
    double z_lo, z_hi_margin, xy_lo, xy_hi;
    // per frame work
    unsigned char* d_img; size_t img_bytes; int H, W;
    int *d_xin, *d_yin, *d_goodin, *d_idx, *d_goodout; double *d_xout, *d_yout, *d_zout;
    cufftDoubleComplex *d_prof, *d_spec, *d_tmp;   // (nb*2, cross)
    double *d_P, *d_r1, *d_sh;                      // (nb*2)
    double* d_rad;                                  // (nb, half)
    cufftDoubleComplex *d_mir, *d_mirf;             // (nb, 2*half-1)
    cufftHandle plan_xy, plan_z;
};

// ---------------------------------------------------------------------------------------------- device helpers --
__device__ __forceinline__ double lv_rint(double v) { return rint(v); }   // round half to even
__device__ __forceinline__ cufftDoubleComplex cmul(cufftDoubleComplex a, cufftDoubleComplex b) {
    return make_cuDoubleComplex(a.x * b.x - a.y * b.y, a.x * b.y + a.y * b.x);
}

// least-squares parabola through NPTS points (xs, ys) with weights w (nullptr = unweighted): returns a2, a1, a0
__device__ void quadfit3(const double* xs, const double* ys, const double* w, double* a2, double* a1, double* a0) {
    double m[3][3] = {{0, 0, 0}, {0, 0, 0}, {0, 0, 0}}, v[3] = {0, 0, 0};
    for (int i = 0; i < NPTS; i++) {
        double x = xs[i], wi = w ? w[i] : 1.0, b[3] = {x * x, x, 1.0};
        for (int r = 0; r < 3; r++) { for (int c = 0; c < 3; c++) m[r][c] += wi * b[r] * b[c]; v[r] += wi * b[r] * ys[i]; }
    }
    // Gaussian elimination with partial pivoting (3x3)
    for (int c = 0; c < 3; c++) {
        int p = c; for (int r = c + 1; r < 3; r++) if (fabs(m[r][c]) > fabs(m[p][c])) p = r;
        if (p != c) { for (int k = 0; k < 3; k++) { double t = m[c][k]; m[c][k] = m[p][k]; m[p][k] = t; } double t = v[c]; v[c] = v[p]; v[p] = t; }
        for (int r = c + 1; r < 3; r++) { double f = m[r][c] / m[c][c]; for (int k = c; k < 3; k++) m[r][k] -= f * m[c][k]; v[r] -= f * v[c]; }
    }
    double s[3];
    for (int r = 2; r >= 0; r--) { double acc = v[r]; for (int k = r + 1; k < 3; k++) acc -= m[r][k] * s[k]; s[r] = acc / m[r][r]; }
    *a2 = s[0]; *a1 = s[1]; *a0 = s[2];
}

// --------------------------------------------------------------------------------------------- K1: cross profiles --
// one block per (bead, axis); threads = cross. along-x: mean over `arm` rows at column h-half+j; along-y: mean over
// `arm` columns at row h-half+j. SGL sum / SGL arm (the VI's To SGL + Add Array Elements), then prep: subtract the mean
// of the first n_end and the "last" n_end points indexed cross - i (i = 0 out of range -> 0), multiply by win_rs.
__global__ void k_profiles(const unsigned char* img, int H, int W, const int* xin, const int* yin, const int* goodin,
                           int cross, int half, int h, int arm, int n_end, const double* win_rs, cufftDoubleComplex* prof) {
    int bead = blockIdx.x >> 1, axis = blockIdx.x & 1, j = threadIdx.x;
    __shared__ double s_p[CROSS_MAX]; __shared__ double s_red[64];
    if (!goodin[bead]) { if (j < cross) prof[blockIdx.x * cross + j] = make_cuDoubleComplex(0, 0); return; }
    int x0 = xin[bead] - h, y0 = yin[bead] - h;      // sub-image origin
    int arm2 = (int)lv_rint(arm / 2.0);
    float sum = 0.f;
    if (j < cross) {
        if (axis == 0) { int col = x0 + (h - half + j); for (int i = 0; i < arm; i++) sum += (float)img[(size_t)(y0 + h - arm2 + i) * W + col]; }
        else           { int row = y0 + (h - half + j); for (int i = 0; i < arm; i++) sum += (float)img[(size_t)row * W + (x0 + h - arm2 + i)]; }
        s_p[j] = (double)(sum / (float)arm);
    }
    __syncthreads();
    // base = (sum_{i<n_end} p[i] + sum_{i<n_end} p[cross - i]) / (2 n_end), p[cross] = 0
    if (j < 64) {
        double acc = 0;
        for (int i = j; i < n_end; i += 64) { acc += s_p[i]; int q = cross - i; if (q < cross) acc += s_p[q]; }
        s_red[j] = acc;
    }
    __syncthreads();
    for (int st = 32; st > 0; st >>= 1) { if (j < st) s_red[j] += s_red[j + st]; __syncthreads(); }
    double base = s_red[0] / (2.0 * n_end);
    if (j < cross) prof[blockIdx.x * cross + j] = make_cuDoubleComplex((s_p[j] - base) * win_rs[j], 0.0);
}

// ------------------------------------------------------------------------------ K2: window + square the spectrum --
__global__ void k_win_square(cufftDoubleComplex* spec, const double* win_h, int cross) {
    int row = blockIdx.x, j = threadIdx.x;
    if (j < cross) { cufftDoubleComplex F = spec[row * cross + j]; F.x *= win_h[j]; F.y *= win_h[j]; spec[row * cross + j] = cmul(F, F); }
}

// ------------------------------------------------------- K3: |IFFT| rotated, argmax, parabola, phase shift for next round --
// round 0: P1 -> r1 = rint(P1), d = P1 - r1 ; round 1: out1 = P2 - r1, d = out1 ; round 2: out2 = P3 - r1.  P accumulates.
__global__ void k_peak_shift(const cufftDoubleComplex* tmp, cufftDoubleComplex* spec, int cross, int half, int round,
                             double* P, double* r1v) {
    int row = blockIdx.x, j = threadIdx.x;
    __shared__ double s_c[CROSS_MAX]; __shared__ double s_v[64]; __shared__ int s_i[64]; __shared__ double s_d;
    if (j < cross) {                                    // Rotate 1D Array by half: c[j] = |x[(j - half) mod cross]| / cross
        int src = j - half; if (src < 0) src += cross;
        cufftDoubleComplex v = tmp[row * cross + src];
        s_c[j] = sqrt(v.x * v.x + v.y * v.y) / cross;
    }
    __syncthreads();
    if (j < 64) {                                        // argmax, first maximum
        double best = -1e300; int bi = 0;
        for (int i = j; i < cross; i += 64) if (s_c[i] > best) { best = s_c[i]; bi = i; }
        s_v[j] = best; s_i[j] = bi;
    }
    __syncthreads();
    for (int st = 32; st > 0; st >>= 1) {
        if (j < st) { if (s_v[j + st] > s_v[j] || (s_v[j + st] == s_v[j] && s_i[j + st] < s_i[j])) { s_v[j] = s_v[j + st]; s_i[j] = s_i[j + st]; } }
        __syncthreads();
    }
    if (j == 0) {
        int lo = s_i[0] - NPTS / 2; double xs[NPTS], ys[NPTS];
        for (int i = 0; i < NPTS; i++) { int q = lo + i; xs[i] = (double)q; ys[i] = (q >= 0 && q < cross) ? s_c[q] : 0.0; }
        double a2, a1, a0; quadfit3(xs, ys, nullptr, &a2, &a1, &a0);
        double Pk = -(a1 / a2) / 2.0, d;
        if (round == 0) { double r1 = lv_rint(Pk); r1v[row] = r1; P[row] = Pk; d = Pk - r1; }
        else { double out = Pk - r1v[row]; P[row] += out; d = out; }
        s_d = d;
    }
    __syncthreads();
    if (round < 2 && j < cross) {                       // phase ramp on the current spectrum: a_j = j (j <= half) else j - cross
        double a = (j > half) ? (double)(j - cross) : (double)j;
        double th = 2.0 * M_PI / cross * s_d * a;
        cufftDoubleComplex S = spec[row * cross + j];
        spec[row * cross + j] = cmul(S, make_cuDoubleComplex(cos(th), sin(th)));
    }
}

// ------------------------------------------------------------------------------ K4: radial profile + mirror --
// one block per bead, threads = cross rows. Centre in sub-image coordinates: (h + shift_x, h + shift_y).
__global__ void k_radial(const unsigned char* img, int H, int W, const int* xin, const int* yin, const int* goodin,
                         const double* P, int cross, int half, int h, double* xout, double* yout, double* rad, cufftDoubleComplex* mir) {
    int bead = blockIdx.x, i = threadIdx.x;
    __shared__ double s_s[CROSS_MAX / 2 + 1], s_w[CROSS_MAX / 2 + 1];
    if (i <= half) { s_s[i] = 0; s_w[i] = 0; }
    __syncthreads();
    if (!goodin[bead]) { if (i == 0) { xout[bead] = -1; yout[bead] = -1; } if (i < half) rad[bead * half + i] = 0; return; }
    double shx = (P[2 * bead] - half) / 2.0, shy = (P[2 * bead + 1] - half) / 2.0;
    if (i == 0) { xout[bead] = xin[bead] + shx; yout[bead] = yin[bead] + shy; }
    double xc = h + shx, yc = h + shy;
    int x0 = (int)ceil(xc) - half, y0 = (int)ceil(yc) - half;            // window origin in the sub-image
    double cx = half + (xc - ceil(xc)), cy = half + (yc - ceil(yc));
    int sx0 = xin[bead] - h, sy0 = yin[bead] - h;                          // sub-image origin in the image
    if (i < cross) {
        double dy = cy - i, dy2 = dy * dy, c = sqrt((double)half * half - dy2);
        int N = (int)ceil(2 * c), j0 = (int)ceil(cx - c);
        for (int kk = 0; kk < N; kk++) {
            int j = j0 + kk; if (j < 0 || j >= cross) continue;
            double p = (double)img[(size_t)(sy0 + y0 + i) * W + (sx0 + x0 + j)];
            double dx = cx - j, r = sqrt(dx * dx + dy2), rf = floor(r), fr = r - rf; int ri = (int)rf;
            if (ri < half) { atomicAdd(&s_s[ri], (1 - fr) * p); atomicAdd(&s_w[ri], 1 - fr); }
            if (ri + 1 < half) { atomicAdd(&s_s[ri + 1], fr * p); atomicAdd(&s_w[ri + 1], fr); }
        }
    }
    __syncthreads();
    if (i < half) {
        float v = (float)(s_s[i] / s_w[i]);                                // the VI holds the profile in SGL
        rad[bead * half + i] = (double)v;
    }
    __syncthreads();
    // mirrored = reverse(rad[1:]) ++ rad   (length 2*half-1, r = 0 at index half-1)
    int n = 2 * half - 1;
    for (int q = i; q < n; q += blockDim.x) {
        int r = (q >= half - 1) ? (q - (half - 1)) : (half - 1 - q);
        mir[bead * n + q] = make_cuDoubleComplex(rad[bead * half + r], 0.0);
    }
}

__global__ void k_cosband(cufftDoubleComplex* mirf, const cufftDoubleComplex* cosband, int n) {
    int bead = blockIdx.x, q = threadIdx.x;
    for (; q < n; q += blockDim.x) mirf[bead * n + q] = cmul(mirf[bead * n + q], cosband[bead * n + q]);
}

// ------------------------------------------------------------ K5: corkscrew, fit to cal, phases, quadratic fit, z --
__global__ void k_z(const cufftDoubleComplex* mir, const int* forget, const double* zstep, const double* real, const double* ampl,
                    const cufftDoubleComplex* cork, int S, int half, const int* goodin, const double* xout, const double* yout,
                    double z_lo, double z_hi_margin, double xy_lo, double xy_hi, int W, int H,
                    double* zout, int* idxout, int* goodout) {
    int bead = blockIdx.x, t = threadIdx.x; int n = 2 * half - 1;
    __shared__ double s_re[CROSS_MAX / 2], s_im[CROSS_MAX / 2], s_abs[CROSS_MAX / 2];
    __shared__ double s_ssd[256]; __shared__ int s_idx; __shared__ double s_ph[NPTS], s_num[NPTS][32], s_den[NPTS][32];
    if (!goodin[bead]) { if (t == 0) { zout[bead] = -1; idxout[bead] = -1; goodout[bead] = 0; } return; }
    int f = forget[bead];
    for (int r = t; r < half; r += blockDim.x) {                            // corkscrew: out[half-1+r] / n, r >= forget
        if (r >= f) { cufftDoubleComplex v = mir[bead * n + (half - 1 + r)]; s_re[r] = v.x / n; s_im[r] = v.y / n; }
        else { s_re[r] = 0; s_im[r] = 0; }
        s_abs[r] = sqrt(s_re[r] * s_re[r] + s_im[r] * s_im[r]);
    }
    __syncthreads();
    for (int s = t; s < S; s += blockDim.x) {                               // SSD of prepped I(r) (= real part) vs cal real
        double acc = 0; const double* row = real + ((size_t)bead * S + s) * half;
        for (int r = f; r < half; r++) { double d = s_re[r] - row[r]; acc += d * d; }
        s_ssd[s] = acc;
    }
    __syncthreads();
    if (t == 0) { int bi = 0; for (int s = 1; s < S; s++) if (s_ssd[s] < s_ssd[bi]) bi = s; s_idx = bi; }
    __syncthreads();
    int idx = s_idx;
    // phases over slices idx-2 .. idx+2: w = |c| * ampl ; theta = arg(c / cal) = arg(c * conj(cal))
    int lane = t & 31, wid = t >> 5;                                        // 32 threads per slice (blockDim >= 160)
    if (wid < NPTS) {
        int s0 = (idx - 2 < 0) ? 0 : idx - 2; int s = s0 + wid; /* v3 D3 = D1 */ double num = 0, den = 0;
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
        if (idx + 2 >= S /* v3 D3 = D2 */) zi = (double)idx;                  // LabVIEW at the stack edge: fit fails -> P(0) = 0
        else {
            const double W5[NPTS] = {(double)0.4f, (double)0.8f, 1.0, (double)0.8f, (double)0.4f} /* v3 D4 */; double ys[NPTS], a2, a1, a0;
            for (int i = 0; i < NPTS; i++) ys[i] = (double)(i - NPTS / 2);
            quadfit3(s_ph, ys, W5, &a2, &a1, &a0); zi = idx + a0;
        }
        zout[bead] = zi * zstep[bead]; idxout[bead] = idx;
        double x = xout[bead], y = yout[bead];
        int bad = (zi > (S - z_hi_margin)) || (zi < z_lo) || (x < xy_lo) || (x > W - xy_hi) || (y < xy_lo) || (y > H - xy_hi);
        goodout[bead] = bad ? 0 : 1;
    }
}

// ---------------------------------------------------------------------------------------------------- host API --
API const char* mt_gpu_last_error() { return g_err; }

API int mt_gpu_init(int cross, int n_slices, int nb_max, const double* win_rs, const double* win_h, void** handle) {
    if (cross > CROSS_MAX || nb_max < 1) { snprintf(g_err, sizeof g_err, "bad cross/nb"); return -1; }
    Ctx* c = (Ctx*)calloc(1, sizeof(Ctx));
    c->cross = cross; c->half = (int)rint(cross / 2.0); c->k_half = 0.6; c->h = (int)rint(cross * c->k_half); c->arm = 10;
    c->n_end = (int)rint(cross / 4.0); c->S = n_slices; c->nb_alloc = nb_max; c->nb = 0;
    c->z_lo = 2; c->z_hi_margin = 3; c->xy_lo = c->h; c->xy_hi = c->h;
    int half = c->half, nb = nb_max, n = 2 * half - 1;
    CK(cudaMalloc(&c->d_win_rs, cross * sizeof(double))); CK(cudaMalloc(&c->d_win_h, cross * sizeof(double)));
    CK(cudaMemcpy(c->d_win_rs, win_rs, cross * sizeof(double), cudaMemcpyHostToDevice));
    CK(cudaMemcpy(c->d_win_h, win_h, cross * sizeof(double), cudaMemcpyHostToDevice));
    CK(cudaMalloc(&c->d_forget, nb * sizeof(int))); CK(cudaMalloc(&c->d_zstep, nb * sizeof(double)));
    CK(cudaMalloc(&c->d_cosband, (size_t)nb * n * sizeof(cufftDoubleComplex)));
    CK(cudaMalloc(&c->d_real, (size_t)nb * n_slices * half * sizeof(double))); CK(cudaMalloc(&c->d_ampl, (size_t)nb * n_slices * half * sizeof(double)));
    CK(cudaMalloc(&c->d_cork, (size_t)nb * n_slices * half * sizeof(cufftDoubleComplex)));
    CK(cudaMemset(c->d_real, 0, (size_t)nb * n_slices * half * sizeof(double))); CK(cudaMemset(c->d_ampl, 0, (size_t)nb * n_slices * half * sizeof(double)));
    CK(cudaMemset(c->d_cork, 0, (size_t)nb * n_slices * half * sizeof(cufftDoubleComplex)));
    CK(cudaMalloc(&c->d_xin, nb * sizeof(int))); CK(cudaMalloc(&c->d_yin, nb * sizeof(int))); CK(cudaMalloc(&c->d_goodin, nb * sizeof(int)));
    CK(cudaMalloc(&c->d_idx, nb * sizeof(int))); CK(cudaMalloc(&c->d_goodout, nb * sizeof(int)));
    CK(cudaMalloc(&c->d_xout, nb * sizeof(double))); CK(cudaMalloc(&c->d_yout, nb * sizeof(double))); CK(cudaMalloc(&c->d_zout, nb * sizeof(double)));
    CK(cudaMalloc(&c->d_prof, (size_t)nb * 2 * cross * sizeof(cufftDoubleComplex))); CK(cudaMalloc(&c->d_spec, (size_t)nb * 2 * cross * sizeof(cufftDoubleComplex)));
    CK(cudaMalloc(&c->d_tmp, (size_t)nb * 2 * cross * sizeof(cufftDoubleComplex)));
    CK(cudaMalloc(&c->d_P, nb * 2 * sizeof(double))); CK(cudaMalloc(&c->d_r1, nb * 2 * sizeof(double))); CK(cudaMalloc(&c->d_sh, nb * 2 * sizeof(double)));
    CK(cudaMalloc(&c->d_rad, (size_t)nb * half * sizeof(double)));
    CK(cudaMalloc(&c->d_mir, (size_t)nb * n * sizeof(cufftDoubleComplex))); CK(cudaMalloc(&c->d_mirf, (size_t)nb * n * sizeof(cufftDoubleComplex)));
    CKF(cufftPlan1d(&c->plan_xy, cross, CUFFT_Z2Z, nb * 2));
    CKF(cufftPlan1d(&c->plan_z, n, CUFFT_Z2Z, nb));
    *handle = c; return 0;
}

// per-bead calibration: cosband (>= 2*half-1 complex, extra ignored), real/ampl/cork are S x len row-major with len = half - forget
API int mt_gpu_set_bead(void* handle, int b, int forget, double zstep, const double* cosband_re, const double* cosband_im,
                        const double* real, const double* ampl, const double* cork_re, const double* cork_im, int len) {
    Ctx* c = (Ctx*)handle; int half = c->half, n = 2 * half - 1, S = c->S;
    if (b < 0 || b >= c->nb_alloc || len != half - forget) { snprintf(g_err, sizeof g_err, "set_bead: bad index/len (len must be half - forget)"); return -1; }
    CK(cudaMemcpy(c->d_forget + b, &forget, sizeof(int), cudaMemcpyHostToDevice));
    CK(cudaMemcpy(c->d_zstep + b, &zstep, sizeof(double), cudaMemcpyHostToDevice));
    cufftDoubleComplex* cb = (cufftDoubleComplex*)malloc(n * sizeof(cufftDoubleComplex));
    for (int q = 0; q < n; q++) cb[q] = make_cuDoubleComplex(cosband_re[q], cosband_im ? cosband_im[q] : 0.0);
    CK(cudaMemcpy(c->d_cosband + (size_t)b * n, cb, n * sizeof(cufftDoubleComplex), cudaMemcpyHostToDevice)); free(cb);
    double* pr = (double*)calloc((size_t)S * half, sizeof(double)); double* pa = (double*)calloc((size_t)S * half, sizeof(double));
    cufftDoubleComplex* pc = (cufftDoubleComplex*)calloc((size_t)S * half, sizeof(cufftDoubleComplex));
    for (int s = 0; s < S; s++) for (int r = 0; r < len; r++) {
        pr[s * half + forget + r] = real[s * len + r]; pa[s * half + forget + r] = ampl[s * len + r];
        pc[s * half + forget + r] = make_cuDoubleComplex(cork_re[s * len + r], cork_im[s * len + r]);
    }
    CK(cudaMemcpy(c->d_real + (size_t)b * S * half, pr, (size_t)S * half * sizeof(double), cudaMemcpyHostToDevice));
    CK(cudaMemcpy(c->d_ampl + (size_t)b * S * half, pa, (size_t)S * half * sizeof(double), cudaMemcpyHostToDevice));
    CK(cudaMemcpy(c->d_cork + (size_t)b * S * half, pc, (size_t)S * half * sizeof(cufftDoubleComplex), cudaMemcpyHostToDevice));
    free(pr); free(pa); free(pc);
    if (b + 1 > c->nb) c->nb = b + 1;
    return 0;
}

API int mt_gpu_set_bounds(void* handle, double z_lo, double z_hi_margin, double xy_lo, double xy_hi) {
    Ctx* c = (Ctx*)handle; c->z_lo = z_lo; c->z_hi_margin = z_hi_margin; c->xy_lo = xy_lo; c->xy_hi = xy_hi; return 0;
}

API int mt_gpu_track(void* handle, const unsigned char* image, int H, int W, int nb, const int* x_in, const int* y_in, const int* good_in,
                     double* x_out, double* y_out, double* z_out, int* idx_out, int* good_out) {
    Ctx* c = (Ctx*)handle; int cross = c->cross, half = c->half, n = 2 * half - 1;
    if (nb < 1 || nb > c->nb_alloc) { snprintf(g_err, sizeof g_err, "track: nb out of range"); return -1; }
    size_t bytes = (size_t)H * W;
    if (bytes != c->img_bytes) { if (c->d_img) cudaFree(c->d_img); CK(cudaMalloc(&c->d_img, bytes)); c->img_bytes = bytes; }
    LARGE_INTEGER qf, q0, q1, q2, q3; QueryPerformanceFrequency(&qf); QueryPerformanceCounter(&q0);
    CK(cudaMemcpy(c->d_img, image, bytes, cudaMemcpyHostToDevice));
    CK(cudaMemcpy(c->d_xin, x_in, nb * sizeof(int), cudaMemcpyHostToDevice)); CK(cudaMemcpy(c->d_yin, y_in, nb * sizeof(int), cudaMemcpyHostToDevice));
    CK(cudaMemcpy(c->d_goodin, good_in, nb * sizeof(int), cudaMemcpyHostToDevice));
    QueryPerformanceCounter(&q1); static cudaEvent_t ev0 = nullptr, ev1 = nullptr; if (!ev0) { cudaEventCreate(&ev0); cudaEventCreate(&ev1); } cudaEventRecord(ev0, 0);
    // XY
    k_profiles<<<nb * 2, cross>>>(c->d_img, H, W, c->d_xin, c->d_yin, c->d_goodin, cross, half, c->h, c->arm, c->n_end, c->d_win_rs, c->d_prof);
    if (nb != c->nb_alloc) { cufftDestroy(c->plan_xy); CKF(cufftPlan1d(&c->plan_xy, cross, CUFFT_Z2Z, nb * 2)); cufftDestroy(c->plan_z); CKF(cufftPlan1d(&c->plan_z, n, CUFFT_Z2Z, nb)); c->nb_alloc = nb; }
    CKF(cufftExecZ2Z(c->plan_xy, c->d_prof, c->d_spec, CUFFT_FORWARD));
    k_win_square<<<nb * 2, cross>>>(c->d_spec, c->d_win_h, cross);
    for (int round = 0; round < 3; round++) {
        CKF(cufftExecZ2Z(c->plan_xy, c->d_spec, c->d_tmp, CUFFT_INVERSE));
        k_peak_shift<<<nb * 2, cross>>>(c->d_tmp, c->d_spec, cross, half, round, c->d_P, c->d_r1);
    }
    // Z
    k_radial<<<nb, cross>>>(c->d_img, H, W, c->d_xin, c->d_yin, c->d_goodin, c->d_P, cross, half, c->h, c->d_xout, c->d_yout, c->d_rad, c->d_mir);
    CKF(cufftExecZ2Z(c->plan_z, c->d_mir, c->d_mirf, CUFFT_FORWARD));
    k_cosband<<<nb, 128>>>(c->d_mirf, c->d_cosband, n);
    CKF(cufftExecZ2Z(c->plan_z, c->d_mirf, c->d_mir, CUFFT_INVERSE));
    k_z<<<nb, 256>>>(c->d_mir, c->d_forget, c->d_zstep, c->d_real, c->d_ampl, c->d_cork, c->S, half, c->d_goodin, c->d_xout, c->d_yout,
                     c->z_lo, c->z_hi_margin, c->xy_lo, c->xy_hi, W, H, c->d_zout, c->d_idx, c->d_goodout);
    CK(cudaGetLastError());
    cudaEventRecord(ev1, 0); CK(cudaStreamSynchronize(0)); QueryPerformanceCounter(&q2); { float ms = 0; cudaEventElapsedTime(&ms, ev0, ev1); g_t_ev = ms; }
    CK(cudaMemcpy(x_out, c->d_xout, nb * sizeof(double), cudaMemcpyDeviceToHost)); CK(cudaMemcpy(y_out, c->d_yout, nb * sizeof(double), cudaMemcpyDeviceToHost));
    CK(cudaMemcpy(z_out, c->d_zout, nb * sizeof(double), cudaMemcpyDeviceToHost)); CK(cudaMemcpy(idx_out, c->d_idx, nb * sizeof(int), cudaMemcpyDeviceToHost));
    CK(cudaMemcpy(good_out, c->d_goodout, nb * sizeof(int), cudaMemcpyDeviceToHost));
    QueryPerformanceCounter(&q3); g_t_up = 1e3 * (double)(q1.QuadPart - q0.QuadPart) / qf.QuadPart; g_t_gpu = 1e3 * (double)(q2.QuadPart - q1.QuadPart) / qf.QuadPart; g_t_dn = 1e3 * (double)(q3.QuadPart - q2.QuadPart) / qf.QuadPart;
    return 0;
}

API int mt_gpu_keepalive(int on);
API int mt_gpu_free(void* handle) {
    mt_gpu_keepalive(0);
    Ctx* c = (Ctx*)handle; if (!c) return 0;
    cufftDestroy(c->plan_xy); cufftDestroy(c->plan_z);
    void* ptrs[] = {c->d_win_rs, c->d_win_h, c->d_forget, c->d_zstep, c->d_cosband, c->d_real, c->d_ampl, c->d_cork, c->d_img, c->d_xin, c->d_yin, c->d_goodin,
                    c->d_idx, c->d_goodout, c->d_xout, c->d_yout, c->d_zout, c->d_prof, c->d_spec, c->d_tmp, c->d_P, c->d_r1, c->d_sh, c->d_rad, c->d_mir, c->d_mirf};
    for (size_t i = 0; i < sizeof ptrs / sizeof ptrs[0]; i++) if (ptrs[i]) cudaFree(ptrs[i]);
    free(c); return 0;
}

// =============================================================================================== LabVIEW entry point ==
// The wrapper VI reuses the Call Library Function Node copied from the Saleh-lab demo (TrackBatchOfImagesWithGPU.vi),
// whose configuration is: C calling convention, 17 parameters — ints by value, LabVIEW handles ("Adapt to Type"), one C
// string — and whose function name is the decorated  ?GPUTracking@@YAHHHHHHPAPAUArray1dInt@@0HHPAPAUImage@@PAPAUArray2d@@22
// PAPAUArrayCluster@@PAPAUBoolArray@@PADPAPAUArray1d@@@Z  (exported under that name by mt_track.def).  The wrapper wires
// OUR types into the adapt-to-type parameters, so the handle layouts below are what LabVIEW 64-bit passes (pack 8):
//   x      : DBL[3*nb]  'x,y,z array'            (in)          y     : DBL[cross]  win_h ('cosine window for Hilbert')
//   image  : U8[rows][cols]                       xout  : DBL[3*nb]  'x,y,z array' (in/out -> 'x,y,z array out')
//   yout   : I32[nb]    'pos in cal image' (in/out)             zout  : BOOL[nb]  'Bead is good?' (in/out)
//   calibration : array of {I32 forget; SGL zstep; H cosband(DBL[]); H ampl(DBL[][]); H cork(CDB[][]); H real(DBL[][]); I32 nslices}
//   BeadStatus  : BOOL[nb] 'Bead is good? array in'            text  : C string (status out, >= 64 chars)   test : DBL[cross] win_rs
//   threads/DIM1..4/crossthickness : ignored.  Returns 0 on success, negative on layout/CUDA errors (text says why).
#include "fused.inc"

#pragma pack(push, 8)
struct LvArr1D  { int32_t n; int32_t pad; double d[1]; };       // DBL 1-D: 4-byte pad after the length (8-byte data alignment)
struct LvArrI32 { int32_t n; int32_t d[1]; };
struct LvArrU8  { int32_t n; uint8_t d[1]; };
struct LvArr2U8 { int32_t pages, rows, cols; uint8_t d[1]; };   // the CLFN's 'Array of Images' is a 3-D U8 array (pages x rows x cols; dump 2026-09-08 10:5x: 1 x 1024 x 1280)
struct LvArr2D  { int32_t rows, cols; double d[1]; };
struct LvArr2C  { int32_t rows, cols; double d[1]; };            // CDB 2-D, interleaved re, im
struct LvArr1F  { int32_t n; float d[1]; };                        // SGL 1-D: data follows the length directly
struct LvArr2F  { int32_t rows, cols; float d[1]; };               // SGL 2-D
// The calibration cluster exactly as LabVIEW 2026 (64-bit) hands it over - read off a raw byte dump (tools/gpu/dump.inc,
// decode_dump.py, 2026-09-08 09:58): {I32 forget; pad; DBL z step; H cosband (DBL 1-D); H ampl (DBL 2-D); H cork (CDB 2-D);
// H real (DBL 2-D); I32 # slices; pad} = 56 bytes per element, array header {I32 n; pad}.  (The Saleh C header's float
// zstep / float arrays describe their 2013 32-bit build, not this VI's wire types.)
struct LvCal    { int32_t forget; int32_t pad0; double zstep; LvArr1D** cosband; LvArr2D** ampl; LvArr2C** cork; LvArr2D** real; int32_t nslices; int32_t pad1; };
struct LvCalArr { int32_t n; int32_t pad; LvCal c[1]; };
#pragma pack(pop)

static void* g_ctx = nullptr; static int g_nb = 0, g_cross = 0, g_S = 0; static unsigned long long g_calsig = 0;


#include "dump.inc"

// Parameter types are FIXED by the donor CLFN (TrackBatchOfImagesWithGPU.vi, Saleh datatypes.h; decorated export
// ?GPUTracking@@YAHHHHHHPAPAUArray1dInt@@0HHPAPAUImage@@PAPAUArray2d@@22PAPAUArrayCluster@@PAPAUBoolArray@@PADPAPAUArray1d@@@Z)
// and are SINGLE precision (COM round-trip 0.1 -> 0.10000000149 on X/Y/Z Output and Test Array, 2026-09-08 09:5x):
//   X Array I32[2 nb] = x_in, y_in (integers, the kernel's I32 start positions)  |  Y Array I32[nb] = 'pos in cal image' IN/OUT
//   Cross Size, Cross Thickness  |  Array of Images U8[rows][cols]  |  X Output SGL 2-D with rows*cols == 9 nb = OUTPUT x,y,z,
//   each DBL encoded LOSSLESSLY as three exact SGL integers (hi = floor(v), mid = floor(frac 2^24), lo = floor(rest 2^24));
//   decode v = hi + mid 2^-24 + lo 2^-48 (error < 3.6e-15)  |  Y Output, Z Output SGL 2-D unused  |  Array Cal Cluster (SGL
//   fields)  |  Bead Is Good Array BOOL[nb] IN/OUT  |  Error Message C string >= 60 B (status; file route: cal path in)
//   |  Test Array SGL[cross] = win_rs.   win_h is computed here (see make_win_h), no parameter is left for it.

// ---- CUDA work on a dedicated worker thread (2026-09-08 11:1x): the CLFN runs in LabVIEW's UI thread (ui=1) and every CUDA
// call there took ~3.5-4.5x longer (phase timers), starving the ~100-launch GPU timeline (cudaEvent 3.3 ms vs 0.9 ms offline).
// The caller hands the job to a persistent worker and waits on an event; the worker keeps the primary CUDA context current.
struct TrackJob { void* h; const unsigned char* img; int H, W, nb; const int *xi, *yi, *gi; double *xo, *yo, *zo; int *io, *go; int rc; };
static HANDLE g_wt = nullptr, g_ev_go = nullptr, g_ev_done = nullptr; static TrackJob g_job; static int g_use_worker = 1;
static DWORD WINAPI track_worker(LPVOID) {
    for (;;) {
        WaitForSingleObject(g_ev_go, INFINITE);
        g_job.rc = mt_gpu_track_any(g_job.h, g_job.img, g_job.H, g_job.W, g_job.nb, g_job.xi, g_job.yi, g_job.gi, g_job.xo, g_job.yo, g_job.zo, g_job.io, g_job.go);
        SetEvent(g_ev_done);
    }
}
static int track_via_worker(void* h, const unsigned char* img, int H, int W, int nb, const int* xi, const int* yi, const int* gi, double* xo, double* yo, double* zo, int* io, int* go) {
    if (!g_use_worker) return mt_gpu_track_any(h, img, H, W, nb, xi, yi, gi, xo, yo, zo, io, go);
    if (!g_wt) { g_ev_go = CreateEventA(nullptr, FALSE, FALSE, nullptr); g_ev_done = CreateEventA(nullptr, FALSE, FALSE, nullptr); g_wt = CreateThread(nullptr, 0, track_worker, nullptr, 0, nullptr); }
    g_job = TrackJob{h, img, H, W, nb, xi, yi, gi, xo, yo, zo, io, go, -99};
    SetEvent(g_ev_go); WaitForSingleObject(g_ev_done, INFINITE);
    return g_job.rc;
}

// host-speed probe: a fixed dependent FP64 loop timed on the calling thread (ms) + process/thread priority - discriminates
// "the whole host thread runs slow in this process" from "GPU submission is slow" (2026-09-08, fused kernel still 4x slower in LabVIEW)
static double cpu_probe_ms() {
    LARGE_INTEGER f, a, b; QueryPerformanceFrequency(&f); QueryPerformanceCounter(&a);
    volatile double x = 1.0; for (int i = 0; i < 2000000; i++) x = x * 1.0000001 + 1e-9;
    QueryPerformanceCounter(&b); return 1e3 * (double)(b.QuadPart - a.QuadPart) / f.QuadPart;
}

static DWORD g_ui_tid = 0;
static BOOL CALLBACK find_ui_thread(HWND h, LPARAM) { DWORD pid = 0; DWORD tid = GetWindowThreadProcessId(h, &pid); if (pid == GetCurrentProcessId() && IsWindowVisible(h)) { g_ui_tid = tid; return FALSE; } return TRUE; }
static int on_ui_thread() { if (!g_ui_tid) EnumWindows(find_ui_thread, 0); return g_ui_tid && GetCurrentThreadId() == g_ui_tid; }

static void make_win_rs(int cross, double* w) {                         // real-space cosine window = cosband LOW 0, HIGH cross-1 (verified 5e-9 px effect)
    for (int i = 0; i < cross; i++) w[i] = 0.5 * (1.0 - cos(2.0 * M_PI * (double)i / (double)(cross - 1)));
}
static void make_win_h(int cross, double* wh) {
    int half = cross / 2;
    for (int i = 0; i < cross; i++) wh[i] = (i <= half) ? 0.5 * (1.0 - cos(2.0 * M_PI * (double)(i + half) / (double)(2 * half))) : 0.0;   // LOW <= i <= HIGH clip
}

static void encode3(double v, float* out) {
    double hi = floor(v); double f = v - hi; double m = floor(f * 16777216.0); double lo = floor((f * 16777216.0 - m) * 16777216.0);
    out[0] = (float)hi; out[1] = (float)m; out[2] = (float)lo;
}

static int check_common(LvArrI32** x, LvArrI32** y, LvArr2U8** image, LvArr2F** xout, LvArrU8** BeadStatus, char* text, LvArr1F** test, int cross, int* nb_out) {
    if (!text) return -10;
    if (!x || !*x || !y || !*y || !image || !*image || !xout || !*xout || !BeadStatus || !*BeadStatus || !test || !*test) { strcpy(text, "null handle"); return -10; }
    int nb = (*y)->n;
    if (nb < 1 || (*x)->n != 2 * nb || (*xout)->rows * (*xout)->cols != 9 * nb || (*BeadStatus)->n != nb || (*test)->n != cross || cross > CROSS_MAX
        || (*image)->pages != 1 || (*image)->rows < cross || (*image)->cols < cross) {
        snprintf(text, 60, "size mismatch nb=%d x=%d out=%dx%d good=%d test=%d img=%dx%dx%d", nb, (*x)->n, (*xout)->rows, (*xout)->cols, (*BeadStatus)->n, (*test)->n, (*image)->pages, (*image)->rows, (*image)->cols); return -11;
    }
    *nb_out = nb; return 0;
}

static int run_track(int nb, LvArrI32** x, LvArr2U8** image, LvArr2F** xout, LvArrI32** y, LvArrU8** BeadStatus, char* text) {
    LARGE_INTEGER f0, t0, t1; QueryPerformanceFrequency(&f0); QueryPerformanceCounter(&t0);          // DLL-internal time, reported in the status
    int H = (*image)->rows, W = (*image)->cols;
    int* xi = (int*)malloc(nb * sizeof(int)); int* yi = (int*)malloc(nb * sizeof(int)); int* gi = (int*)malloc(nb * sizeof(int));
    double* xo = (double*)malloc(nb * sizeof(double)); double* yo = (double*)malloc(nb * sizeof(double)); double* zo = (double*)malloc(nb * sizeof(double));
    int* io = (int*)malloc(nb * sizeof(int)); int* go = (int*)malloc(nb * sizeof(int));
    for (int b = 0; b < nb; b++) { xi[b] = (*x)->d[2 * b]; yi[b] = (*x)->d[2 * b + 1]; gi[b] = (*BeadStatus)->d[b] ? 1 : 0; }
    int rc = track_via_worker(g_ctx, (*image)->d, H, W, nb, xi, yi, gi, xo, yo, zo, io, go);
    if (rc == 0) {                                                  // keep-alive starts AFTER the first successful call: every buffer exists by
        static int ka_init = 0;                                      // then (cudaMalloc/cudaFree synchronise the whole device and would wait forever)
        if (!ka_init) { ka_init = 1; char v[8]; DWORD n = GetEnvironmentVariableA("MT_GPU_KEEPALIVE", v, sizeof v); if (n && v[0] == '1') mt_gpu_keepalive(1); }      // OPT-IN only (MT_GPU_KEEPALIVE=1): the spin kernel deadlocked the work stream in tests
        for (int b = 0; b < nb; b++) {
            encode3(xo[b], (*xout)->d + 9 * b); encode3(yo[b], (*xout)->d + 9 * b + 3); encode3(zo[b], (*xout)->d + 9 * b + 6);
            (*y)->d[b] = io[b]; (*BeadStatus)->d[b] = (uint8_t)(go[b] ? 1 : 0);
        }
        QueryPerformanceCounter(&t1); snprintf(text, 60, "No_Errors t=%.2f u=%.2f k=%.2f e=%.2f ka=%d", 1e3 * (double)(t1.QuadPart - t0.QuadPart) / (double)f0.QuadPart, g_t_up, g_t_gpu, g_t_ev, g_keep_on);   // ms inside the DLL (track + image upload)
    } else { strncpy(text, g_err, 59); text[59] = 0; }
    free(xi); free(yi); free(gi); free(xo); free(yo); free(zo); free(io); free(go);
    return rc;
}

static double* to_double(const float* f, size_t n) { double* d = (double*)malloc(n * sizeof(double)); for (size_t i = 0; i < n; i++) d[i] = (double)f[i]; return d; }

static int cal_plausible(LvCalArr* ca, int half) {
    if (sizeof(LvCal) != 56) return 0;
    for (int b = 0; b < ca->n; b++) {
        LvCal* c = &ca->c[b];
        if (c->forget <= 0 || c->forget >= half || !c->cosband || IsBadReadPtr(c->cosband, 8) || !*c->cosband || IsBadReadPtr(*c->cosband, 8)) return 0;
        if (!c->ampl || IsBadReadPtr(c->ampl, 8) || !*c->ampl || !c->cork || IsBadReadPtr(c->cork, 8) || !*c->cork || !c->real || IsBadReadPtr(c->real, 8) || !*c->real) return 0;
        if ((*c->real)->rows <= 0 || (*c->real)->cols != half - c->forget || (*c->ampl)->cols != half - c->forget || (*c->cork)->cols != half - c->forget) return 0;
    }
    return 1;
}

static unsigned long long cal_signature2(LvCalArr* ca) {
    unsigned long long h = 1469598103934665603ull;
    for (int b = 0; b < ca->n; b++) {
        LvCal* c = &ca->c[b]; const double* r = (*c->real)->d; int n = (*c->real)->rows * (*c->real)->cols;
        h ^= (unsigned long long)c->forget; h *= 1099511628211ull;
        for (int i = 0; i < n; i += 97) { unsigned long long v; memcpy(&v, &r[i], 8); h ^= v; h *= 1099511628211ull; }
    }
    return h ^ (unsigned long long)ca->n;
}

API int GPUTracking_lv(int threads, int DIM1, int DIM2, int DIM3, int DIM4, LvArrI32** x, LvArrI32** y, int cross, int crossthickness,
                       LvArr2U8** image, LvArr2F** xout, LvArr2F** yout, LvArr2F** zout, LvCalArr** calibration, LvArrU8** BeadStatus,
                       char* text, LvArr1F** test) {
    (void)threads; (void)DIM1; (void)DIM2; (void)DIM3; (void)DIM4; (void)crossthickness; (void)yout; (void)zout;
    dump_all((void**)x, (void**)y, (void**)image, (void**)xout, (void**)yout, (void**)zout, (void**)calibration, (void**)BeadStatus, text, (void**)test, cross);
    int nb = 0, rc = check_common(x, y, image, xout, BeadStatus, text, test, cross, &nb); if (rc) return rc;
    if (!calibration || !*calibration || (*calibration)->n != nb) { snprintf(text, 60, "cal clusters %d != nb %d", calibration && *calibration ? (*calibration)->n : -1, nb); return -12; }
    int half = cross / 2;
    if (!cal_plausible(*calibration, half)) { snprintf(text, 60, "cal layout: forget %d zstep %g", (*calibration)->c[0].forget, (*calibration)->c[0].zstep); return -13; }
    int S = (*(*calibration)->c[0].real)->rows;
    if (!g_ctx || g_nb < nb || g_cross != cross || g_S != S) {
        if (g_ctx) { mt_gpu_free(g_ctx); g_ctx = nullptr; }
        double wh[CROSS_MAX]; make_win_h(cross, wh); double* wrs = to_double((*test)->d, cross);
        int rc2 = mt_gpu_init(cross, S, nb, wrs, wh, &g_ctx); free(wrs);
        if (rc2 != 0) { strncpy(text, g_err, 59); text[59] = 0; return -12; }
        g_nb = nb; g_cross = cross; g_S = S; g_calsig = 0;
    }
    unsigned long long sig = cal_signature2(*calibration);
    if (sig != g_calsig) {
        for (int b = 0; b < nb; b++) {
            LvCal* c = &(*calibration)->c[b]; int len = (*c->real)->cols;
            if ((*c->real)->rows != S || (*c->ampl)->rows != S || (*c->cork)->rows != S || (*c->cosband)->n < 2 * half - 1) {
                snprintf(text, 60, "cal layout b%d: rows %d cols %d forget %d", b, (*c->real)->rows, len, c->forget); return -13;
            }
            size_t nn = (size_t)S * len; double* cre = (double*)malloc(nn * sizeof(double)); double* cim = (double*)malloc(nn * sizeof(double));
            for (size_t i = 0; i < nn; i++) { cre[i] = (*c->cork)->d[2 * i]; cim[i] = (*c->cork)->d[2 * i + 1]; }
            int rc2 = mt_gpu_set_bead(g_ctx, b, c->forget, c->zstep, (*c->cosband)->d, nullptr, (*c->real)->d, (*c->ampl)->d, cre, cim, len);
            free(cre); free(cim);
            if (rc2 != 0) { strncpy(text, g_err, 59); text[59] = 0; return -14; }
        }
        g_calsig = sig;
    }
    return run_track(nb, x, image, xout, y, BeadStatus, text);
}

#include "cal_file.inc"

#include "mt2.inc"
