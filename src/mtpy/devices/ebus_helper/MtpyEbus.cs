// Pointer access that pythonnet cannot do: a PvBuffer's data address as a long, and attaching caller-owned memory.
// Built once by mtpy.devices.ebus (csc.exe of the .NET Framework that PvDotNet.dll targets); 2026-11-01.
using System;
using PvDotNet;

namespace Mtpy {
public static class MtpyEbus
{
    public static unsafe long DataAddress(PvBuffer b) { return (long)b.DataPointer; }
    public static unsafe long ImageAddress(PvImage i) { return (long)i.DataPointer; }
    public static unsafe void Attach(PvBuffer b, long address, uint size) { b.Attach((byte*)address, size); }
}
}
