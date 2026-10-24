function [data, header] = read_tra(path)
% READ_TRA  Read a LabVIEW .tra trace file (layout: docs/format/tra-cal.md).
%   [data, header] = read_tra(path)
%   data(:,1) frame, data(:,2) magnet, data(:,3) rotor, then x, y, z per bead (bead 1 = reference bead).
%   Little-endian; the header text is in code page 949.
f = fopen(path, 'r', 'ieee-le');
c = onCleanup(@() fclose(f));
n = fread(f, 1, 'uint32');
header = native2unicode(fread(f, n, 'uint8=>uint8')', 'cp949');
dims = fread(f, 2, 'uint32');
data = fread(f, [dims(2), dims(1)], 'double')';    % stored row-major
end
