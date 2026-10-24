function cal = read_cal(path)
% READ_CAL  Read a LabVIEW .cal calibration file (layout: docs/format/tra-cal.md).
%   Big-endian LabVIEW flattened data. Fields: xy (n x 2), stack (n x S x L), n_slices, bead_i32 (n x 3),
%   z_step (um), n_avg, date, bead_flags (n x 1), nm_per_px.
f = fopen(path, 'r', 'ieee-be');
c = onCleanup(@() fclose(f));
d = fread(f, 2, 'int32');
cal.xy = fread(f, [d(2), d(1)], 'double')';
d = fread(f, 3, 'int32');
cal.stack = permute(reshape(fread(f, prod(d), 'double'), d(3), d(2), d(1)), [3 2 1]);
cal.n_slices = fread(f, 1, 'int32');
d = fread(f, 2, 'int32');
cal.bead_i32 = reshape(fread(f, prod(d), 'int32'), d(2), d(1))';
cal.z_step = fread(f, 1, 'double');
cal.n_avg = fread(f, 1, 'int32');
n = fread(f, 1, 'int32');
cal.date = native2unicode(fread(f, n, 'uint8=>uint8')', 'cp949');
n = fread(f, 1, 'int32');
cal.bead_flags = fread(f, n, 'int32');
cal.nm_per_px = fread(f, 1, 'double');
end
