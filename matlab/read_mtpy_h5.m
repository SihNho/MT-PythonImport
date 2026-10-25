function [data, run] = read_mtpy_h5(path)
% READ_MTPY_H5  Read an mtpy HDF5 v1 run file (layout: docs/format/hdf5-v1.md, "Implemented in WP4" in
% docs/design/api.md).
%   [data, run] = read_mtpy_h5(path)
%   data  legacy mode, like read_tra: one row per TRACKED frame (pipeline drops and tracking errors left out),
%         columns frame, magnet (mm), rotor (deg), then x, y, z per bead in the order of run.beads.bead_id.
%         frame runs over the whole file and never restarts (decision 0016 item 4, owner refinement
%         2026-10-25), as the .tra export: 0 = the first recorded frame of the run; within a segment frame =
%         buffer number - the segment's first recorded buffer number + the segment's offset (a recording off / on
%         gap stays a visible jump); the next segment's first recorded frame = the previous segment's last
%         recorded frame + 1 (buffer numbers restart; the frames between segments are not countable). Rows are
%         sorted by frame (= segment order, then buffer number). run.mt.segment still tells the segments apart.
%   run   extended mode: run.attrs (root attributes), run.mt, run.beads, run.segments, run.recordings,
%         run.events.<kind>, run.meta (the /metadata group). Columns marked as JSON stay text: use jsondecode.
%   Per-frame per-bead datasets are stored [frames x beads]; h5read returns them transposed, so 2-D datasets
%   are transposed back here (3-D ones permuted) to keep frames along the first dimension.
%   NOTE: written in WP4 without MATLAB at hand; the layout it reads is checked from Python, the code itself
%   has not been run in MATLAB yet.
%   TARGET: MATLAB 2026 (owner, decision 0016 item 5; release letter a / b not given). MATLAB is not installed
%   on the development PC; this reader is to be checked in WP6 where MATLAB 2026 is available.
info = h5info(path);
run.attrs = struct();
for k = 1:numel(info.Attributes)
    run.attrs.(matlab.lang.makeValidName(info.Attributes(k).Name)) = info.Attributes(k).Value;
end
for k = 1:numel(info.Groups)
    g = info.Groups(k);
    name = g.Name(2:end);
    if strcmp(name, 'metadata')
        run.meta = read_group(path, g);
    else
        run.(matlab.lang.makeValidName(name)) = read_group(path, g);
    end
end
data = [];
if ~isfield(run, 'mt') || ~isfield(run.mt, 'x_px')
    return
end
ok = run.mt.dropped == 0 & run.mt.track_error == 0;
buf = double(run.mt.buffer_number);
seg = double(run.mt.segment);
shift = zeros(size(buf));                  % frame = buffer number + shift of its segment
nxt = 0;
for s = unique(seg).'                      % unique() sorts: segment order
    b = buf(seg == s);
    shift(seg == s) = nxt - min(b);        % first recorded frame of the segment = previous last + 1 (0 for the first)
    nxt = max(b) - min(b) + nxt + 1;
end
nb = size(run.mt.x_px, 2);
xyz = zeros(sum(ok), 3 * nb);
xyz(:, 1:3:end) = run.mt.x_px(ok, :);
xyz(:, 2:3:end) = run.mt.y_px(ok, :);
xyz(:, 3:3:end) = run.mt.z_um(ok, :);
data = [buf(ok) + shift(ok), run.mt.magnet_mm(ok), run.mt.rotor_deg(ok), xyz];
[~, order] = sort(data(:, 1));             % stable: the .tra row order
data = data(order, :);
end

function s = read_group(path, g)
s = struct();
for k = 1:numel(g.Datasets)
    d = g.Datasets(k);
    v = h5read(path, [g.Name '/' d.Name]);
    n = numel(d.Dataspace.Size);
    if isnumeric(v) && n == 2
        v = v.';
    elseif isnumeric(v) && n == 3
        v = permute(v, [3 2 1]);
    end
    s.(matlab.lang.makeValidName(d.Name)) = v;
end
for k = 1:numel(g.Groups)
    [~, name] = fileparts(g.Groups(k).Name);
    s.(matlab.lang.makeValidName(name)) = read_group(path, g.Groups(k));
end
end
