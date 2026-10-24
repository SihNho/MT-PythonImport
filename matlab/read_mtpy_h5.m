function [data, run] = read_mtpy_h5(path)
% READ_MTPY_H5  Read an mtpy HDF5 v1 run file (layout: docs/format/hdf5-v1.md, "Implemented in WP4" in
% docs/design/api.md).
%   [data, run] = read_mtpy_h5(path)
%   data  legacy mode, like read_tra: one row per TRACKED frame (pipeline drops and tracking errors left out),
%         columns frame, magnet (mm), rotor (deg), then x, y, z per bead in the order of run.beads.bead_id.
%         frame = buffer number - first buffer number of its segment; buffer numbers restart in every segment,
%         so with several segments use run.mt.segment (or the per-segment .tra export) to split the rows.
%   run   extended mode: run.attrs (root attributes), run.mt, run.beads, run.segments, run.recordings,
%         run.events.<kind>, run.meta (the /metadata group). Columns marked as JSON stay text: use jsondecode.
%   Per-frame per-bead datasets are stored [frames x beads]; h5read returns them transposed, so 2-D datasets
%   are transposed back here (3-D ones permuted) to keep frames along the first dimension.
%   NOTE: written in WP4 without MATLAB at hand; the layout it reads is checked from Python, the code itself
%   has not been run in MATLAB yet.
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
first = zeros(size(buf));
for s = unique(seg).'
    k = find(double(run.segments.number) == s, 1);
    f = -1;
    if ~isempty(k)
        f = double(run.segments.first_buffer(k));
    end
    if f < 0
        f = min(buf(seg == s));        % segment end never received: the smallest recorded buffer number
    end
    first(seg == s) = f;
end
nb = size(run.mt.x_px, 2);
xyz = zeros(sum(ok), 3 * nb);
xyz(:, 1:3:end) = run.mt.x_px(ok, :);
xyz(:, 2:3:end) = run.mt.y_px(ok, :);
xyz(:, 3:3:end) = run.mt.z_um(ok, :);
data = [buf(ok) - first(ok), run.mt.magnet_mm(ok), run.mt.rotor_deg(ok), xyz];
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
