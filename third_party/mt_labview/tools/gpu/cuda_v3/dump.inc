// dump.inc - included before the wrapper: on the FIRST call of a LabVIEW entry, write the raw bytes LabVIEW handed us to
// %TEMP%\mt_track_dump.bin so the handle/cluster layout can be decoded offline (tools/gpu/decode_dump.py) instead of guessed.
// Every read is guarded by IsBadReadPtr so a wrong guess produces a short record, not a crash (error 1097).

static void dump_block(FILE* f, const char* tag, const void* p, size_t n) {
    char t[16] = {0}; strncpy(t, tag, 15); fwrite(t, 1, 16, f);
    uint64_t addr = (uint64_t)(uintptr_t)p; fwrite(&addr, 8, 1, f);
    uint32_t ok = (p && !IsBadReadPtr(p, n)) ? 1u : 0u; uint32_t len = ok ? (uint32_t)n : 0u; fwrite(&ok, 4, 1, f); fwrite(&len, 4, 1, f);
    if (ok) fwrite(p, 1, n, f);
}

static void dump_handle(FILE* f, const char* tag, void** h, size_t n) {
    char t2[16]; snprintf(t2, sizeof t2, "%s*", tag); dump_block(f, t2, h, 8);          // the handle itself (pointer to pointer)
    const void* p = (h && !IsBadReadPtr(h, 8)) ? *h : nullptr; dump_block(f, tag, p, n);  // what it points to
}

static void dump_all(void** x, void** y, void** image, void** xout, void** yout, void** zout, void** calibration, void** BeadStatus, char* text, void** test, int cross) {
    static int done = 0; if (done) return; done = 1;
    char path[MAX_PATH]; DWORD n = GetTempPathA(MAX_PATH, path); if (!n) return; strncat(path, "mt_track_dump.bin", MAX_PATH - 1 - strlen(path));
    FILE* f = fopen(path, "wb"); if (!f) return;
    int32_t hdr[2] = {(int32_t)0x4C56444D, cross}; fwrite(hdr, 4, 2, f);                                       // "MDVL", cross
    dump_handle(f, "x", x, 64); dump_handle(f, "y", y, 64); dump_handle(f, "image", image, 32); dump_handle(f, "xout", xout, 64);
    dump_handle(f, "yout", yout, 32); dump_handle(f, "zout", zout, 32); dump_handle(f, "good", BeadStatus, 32); dump_block(f, "text", text, 128);
    dump_handle(f, "test", test, 64); dump_handle(f, "cal", calibration, 8 + 8 * 48);
    // the first cluster element's four handle-shaped fields at every plausible offset: dereference each 8-byte word in [8, 48)
    if (calibration && !IsBadReadPtr(calibration, 8) && *calibration && !IsBadReadPtr(*calibration, 56)) {
        const unsigned char* c = (const unsigned char*)*calibration;
        for (int off = 8; off < 56; off += 8) {
            void** hh; memcpy(&hh, c + off, 8); char tag[16]; snprintf(tag, sizeof tag, "c0@%d", off);
            dump_handle(f, tag, hh, 48);
        }
    }
    fclose(f);
}
