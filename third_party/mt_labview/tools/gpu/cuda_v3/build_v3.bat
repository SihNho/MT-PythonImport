@echo off
rem build_v3.bat - gpuswap dllv3-14 (2026-10-19): copy of build_v2.bat; the output DLL, the .def and the macro set are ARGUMENTS:
rem   build_v3.bat <out.dll> <file.def> [-DCPU_SGL_PREP] [-DCPU_SGL_CENTRE]      (never mt_track.dll / mt_track_v2.dll)
rem (build_v2.bat - gpuswap partB-dllv2-12 (2026-10-18): copy of build.bat that wrote mt_track_v2.dll in cuda_v2\.)
rem build.bat - compile mt_track.cu into mt_track.dll (CUDA 12.6 + MSVC 2022 Build Tools)
rem
rem PORTABILITY (the PC may change - user, 2026-09-13). nvcc 12.6 can emit cubins only up to sm_90, so a future GPU
rem is reached through PTX, which the driver JIT-compiles at load. `-arch=sm_75` alone ALREADY embeds compute_75 PTX
rem (verified: `cuobjdump --list-ptx mt_track.dll` -> mt_track.sm_75.ptx; NVCC docs: `-arch=sm_XX` expands to
rem `--gpu-architecture=compute_XX --gpu-code=sm_XX,compute_XX`), so the old flag was not broken.
rem What the explicit list below adds is NATIVE cubins for the GPUs this rig is actually likely to move to, so those
rem machines skip JIT entirely - no first-call compile latency, and no JIT-vs-SASS numerical question:
rem   sm_75  Turing   RTX 20xx / GTX 16xx  <- this machine (RTX 2060)
rem   sm_86  Ampere   RTX 30xx
rem   sm_89  Ada      RTX 40xx
rem   compute_75 PTX  everything newer - OUR kernels only; see the cuFFT caveat below before trusting Blackwell
rem
rem NOT covered by this file, and required on the target machine:
rem   * cufft64_11.dll must be present (dynamic; cudart is static - `dumpbin -dependents` confirms).
rem     cuFFT IS THE PART THAT BREAKS FIRST, and it is measured, not guessed: under NVIDIA's own forced-JIT
rem     acceptance test (CUDA_FORCE_PTX_JIT=1) our kernels load fine but `cufftPlan1d` returns CUFFT_INTERNAL_ERROR
rem     (isolated: CUDA_CACHE_DISABLE=1 alone passes with identical numbers). cuFFT did not claim Blackwell support
rem     until CUDA 12.9 - so on an RTX 50xx box, deploy the cuFFT redistributable from CUDA 12.8+, not this one.
rem     The soname stays _11 across all of CUDA 12.x, so a newer cuFFT drops in with no relinking.
rem   * driver >= R560 (Windows 560.76) - the CUDA 12.x minor-version floor of 528.33 is NOT enough for a
rem     PTX-dependent binary.
rem   * numerical acceptance must be RE-RUN on the new GPU: cuFFT guarantees bitwise reproducibility only for a
rem     fixed GPU model, so the 1e-6 px agreement is a property of a machine, not of this DLL.
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat" >nul
set CUDA_PATH=C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.6
set PATH=%CUDA_PATH%\bin;%PATH%
if "%~2"=="" (echo usage: build_v3.bat out.dll file.def [macros] & exit /b 2)
if /i "%~1"=="mt_track.dll" (echo REFUSED: never mt_track.dll & exit /b 2)
if /i "%~1"=="mt_track_v2.dll" (echo REFUSED: never mt_track_v2.dll & exit /b 2)
echo BUILD %~1 DEF %~2 MACROS [%~3 %~4]
nvcc --version
set GENCODE=-gencode arch=compute_75,code=sm_75 -gencode arch=compute_86,code=sm_86 -gencode arch=compute_89,code=sm_89 -gencode arch=compute_75,code=compute_75
nvcc -O2 -lineinfo %GENCODE% -allow-unsupported-compiler %~3 %~4 -Xcompiler "/MD /O2 /wd4819 /utf-8" -Xlinker "/DEF:%~2" -shared -o %~1 mt_track.cu -lcufft -luser32 2>&1
if errorlevel 1 (echo BUILD FAILED & exit /b 1)
dir %~1
echo BUILD OK
