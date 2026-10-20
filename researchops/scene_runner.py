"""Child-process runner for registered scene tools. Started only by researchops.scene.run_tool as
`python -I -B scene_runner.py REQUEST.json` inside a private kill-on-close job.

It executes exactly one registered tool with already-validated parameters, reads registered
inputs read-only, and writes only inside the request's out_dir. It never runs shell commands
or anything supplied by a model.
"""
import json
import os
from pathlib import Path
import sys
import traceback


def _inside(path, root):
    path, root = Path(path).resolve(), Path(root).resolve()
    return path == root or root in path.parents


def room_meshes(req, out):
    """Inventory one Scenesmith room exported as glTF (Y-up): collision-mesh sanity per mesh."""
    import numpy as np
    import trimesh
    room = Path(req["inputs"]["room_dir"])
    files = ["floors/floor.gltf"] + sorted("walls/%s/wall.gltf" % d.name for d in (room/"walls").iterdir() if d.is_dir())
    meshes = {}
    for rel in files:
        scene = trimesh.load(room/rel, force="scene")
        mesh = scene.to_geometry() if hasattr(scene, "to_geometry") else scene.dump(concatenate=True)
        lo, hi = mesh.bounds
        meshes[rel] = {"vertices": int(len(mesh.vertices)), "faces": int(len(mesh.faces)),
                       "finite": bool(np.isfinite(mesh.vertices).all()), "watertight_raw": bool(mesh.is_watertight),
                       "watertight_merged": bool(_merged(mesh).is_watertight),
                       "volume_m3": round(float(_merged(mesh).volume), 5) if _merged(mesh).is_watertight else None,
                       "bounds_min": [round(float(v), 4) for v in lo], "bounds_max": [round(float(v), 4) for v in hi],
                       "area_m2": round(float(mesh.area), 4)}
    floor = meshes["floors/floor.gltf"]
    walls = [v for k, v in meshes.items() if k.startswith("walls/")]
    thickness = min(min(w["bounds_max"][2] - w["bounds_min"][2], w["bounds_max"][0] - w["bounds_min"][0]) for w in walls)
    floor_x = floor["bounds_max"][0] - floor["bounds_min"][0]
    floor_z = floor["bounds_max"][2] - floor["bounds_min"][2]
    floor_y = floor["bounds_max"][1] - floor["bounds_min"][1]
    checks = {"all_meshes_nonempty_finite": all(m["faces"] >= 12 and m["finite"] for m in meshes.values()),
              "all_meshes_watertight_after_position_merge": all(m["watertight_merged"] for m in meshes.values()),
              "floor_volume_matches_extent": floor["volume_m3"] is not None and abs(
                  floor["volume_m3"] - (floor["bounds_max"][0] - floor["bounds_min"][0]) * floor_y *
                  (floor["bounds_max"][2] - floor["bounds_min"][2])) <= 1e-3,
              "walls_rise_above_floor": all(w["bounds_max"][1] > floor["bounds_max"][1] + 2.0 for w in walls)}
    result = {"meshes": meshes, "checks": checks, "up_axis": "Y", "units": "m",
              "floor_extent_m": [round(floor_x, 4), round(floor_z, 4)],
              "wall_thickness_m": round(thickness, 4),
              "interior_m": [round(floor_x - 2 * thickness, 4), round(floor_z - 2 * thickness, 4)],
              "floor_top_y_m": floor["bounds_max"][1],
              "wall_height_m": round(max(w["bounds_max"][1] for w in walls) - floor["bounds_max"][1], 4),
              "assumptions": ["single-storey export: the storey rise is taken as the wall height",
                              "interior = floor extent minus two wall thicknesses"]}
    return result


def _merged(mesh):
    copy = mesh.copy()
    copy.merge_vertices(merge_tex=True, merge_norm=True)  # glTF repeats vertices per face/UV; merge by position
    return copy


def _profile(req):
    from buildingsgen.config import load_profile
    return load_profile(req["params"]["profile"])


def measure_stair(path):
    """Measure an authored stair from its geometry: all meshes (handrails included) for the
    footprint, tread tops for the rises. The build record's own footprint is not trusted."""
    import numpy as np
    from pxr import Usd, UsdGeom, UsdPhysics
    stage = Usd.Stage.Open(str(path))
    meshes, tops = [], []
    for prim in stage.Traverse():
        if prim.IsA(UsdGeom.Mesh):
            pts = np.array(UsdGeom.Mesh(prim).GetPointsAttr().Get() or [], dtype=float)
            idx = UsdGeom.Mesh(prim).GetFaceVertexIndicesAttr().Get() or []
            meshes.append({"path": str(prim.GetPath()), "points": len(pts), "indices": len(idx),
                           "finite": bool(len(pts) and np.isfinite(pts).all()),
                           "collider": prim.HasAPI(UsdPhysics.CollisionAPI),
                           "lo": pts.min(axis=0).tolist() if len(pts) else None,
                           "hi": pts.max(axis=0).tolist() if len(pts) else None})
            if "/Treads/" in str(prim.GetPath()) and len(pts):
                tops.append(float(pts[:, 2].max()))
    solid = [m for m in meshes if m["lo"]]
    lo = np.min([m["lo"] for m in solid], axis=0) if solid else np.zeros(3)
    hi = np.max([m["hi"] for m in solid], axis=0) if solid else np.zeros(3)
    return stage, meshes, sorted(tops), sorted([float(hi[0] - lo[0]), float(hi[1] - lo[1])]), float(hi[2] - lo[2])



def _build_inside_sandbox(spec, destination):
    """Keep OpenUSD's accessible-prefix binary search inside the granted private tree.
    File output is copied by Python to the registered path after authoring succeeds.
    No ancestor directory outside this attempt receives an AppContainer permission.
    """
    import shutil
    from buildingsgen.stairs.asset import build_stair_usd
    destination=Path(destination)
    private=destination.parent/"_usd"
    # Each component is deliberately short to stay below Windows MAX_PATH.
    for _ in range(len(destination.parent.parents)+2): private=private/"w"
    private.mkdir(parents=True,exist_ok=True)
    record=build_stair_usd(spec,private/"stair.usda")
    shutil.copyfile(private/"stair.usda",destination)
    shutil.copyfile(private/"traversal_path.json",destination.parent/"traversal_path.json")
    record["stage"]=str(destination)
    return record

def stair_candidates(req, out):
    """Design and actually author every family the profile allows for the rise, measure each
    asset and compare its measured footprint (plus clearance) with the room interior."""
    from buildingsgen.stairs.asset import build_stair_usd
    from buildingsgen.stairs.spec import design_stair
    p = req["params"]
    profile = _profile(req)
    room = sorted(p["room_interior_m"])
    rows = []
    for family in profile.stair.families:
        try:
            spec = design_stair(p["rise_m"], profile.stair, family=family)
        except Exception as exc:  # the library's own envelope refusal is a result, not a crash
            rows.append({"family": family, "designed": False, "reason": type(exc).__name__ + ": " + str(exc)[:300]})
            continue
        _build_inside_sandbox(spec, Path(out)/"candidates"/family/"stair.usda")
        _, _, _, foot, height = measure_stair(Path(out)/"candidates"/family/"stair.usda")
        need = [foot[0] + 2 * p["clearance_m"], foot[1] + 2 * p["clearance_m"]]
        rows.append({"family": family, "designed": True, "spec": spec.as_dict(),
                     "library_footprint_sorted_m": [round(v, 4) for v in sorted(spec.footprint_m())],
                     "footprint_sorted_m": [round(v, 4) for v in foot],
                     "target_floor_rise_m": round(float(p["rise_m"]), 4),
                     "mesh_bbox_height_m": round(height, 4),
                     "needs_with_clearance_m": [round(v, 4) for v in need],
                     "fits_room": need[0] <= room[0] and need[1] <= room[1],
                     "margin_m": [round(room[0] - need[0], 4), round(room[1] - need[1], 4)]})
    return {"profile": p["profile"], "rise_m": p["rise_m"], "room_interior_sorted_m": room,
            "clearance_m": p["clearance_m"], "riser_envelope_m": [profile.stair.min_riser_m, profile.stair.max_riser_m],
            "candidates": rows}


def stair_build(req, out):
    from buildingsgen.stairs.asset import build_stair_usd
    from buildingsgen.stairs.spec import design_stair
    p = req["params"]
    profile = _profile(req)
    spec = design_stair(p["rise_m"], profile.stair, family=p["family"])
    record = _build_inside_sandbox(spec, Path(out)/"stair.usda")
    return json.loads(json.dumps(record, default=str))


def stair_check(req, out):
    """Re-open the built asset and measure it; nothing here trusts the build record."""
    from pxr import UsdGeom
    p = req["params"]
    profile = _profile(req)
    stage, meshes, tops, foot, height = measure_stair(Path(req["inputs"]["stair_usda"]))
    rises = ([tops[0]] + [b - a for a, b in zip(tops, tops[1:])] + [p["rise_m"] - tops[-1]]) if tops else []
    max_riser, min_riser = profile.stair.max_riser_m, profile.stair.min_riser_m
    room = sorted(p["room_interior_m"])
    inside = lambda r: min_riser - 1e-6 <= r <= max_riser + 1e-6
    path = json.loads((Path(req["inputs"]["stair_usda"]).parent/"traversal_path.json").read_text(encoding="utf-8"))
    points = path.get("points_m") or []
    checks = {
        "reopened_by_usd": stage is not None,
        "z_up_metres": UsdGeom.GetStageUpAxis(stage) == "Z" and UsdGeom.GetStageMetersPerUnit(stage) == 1.0,
        "meshes_present_nonempty_finite": bool(meshes) and all(m["points"] >= 8 and m["indices"] >= 12 and m["finite"] for m in meshes),
        "every_mesh_has_collider": bool(meshes) and all(m["collider"] for m in meshes),
        "tread_count_matches_family": len(tops) == p["expected_tread_count"],
        "every_rise_within_envelope": bool(rises) and all(inside(r) for r in rises),
        "first_and_last_rise_within_envelope": bool(rises) and inside(rises[0]) and inside(rises[-1]),
        "footprint_matches_candidate": all(abs(a - b) <= 0.02 for a, b in zip(foot, sorted(p["expected_footprint_m"]))),
        "fits_room_with_clearance": foot[0] + 2 * p["clearance_m"] <= room[0] and foot[1] + 2 * p["clearance_m"] <= room[1],
        "traversal_path_reaches_rise": bool(points) and abs(points[0][2]) <= 0.25 and abs(points[-1][2] - p["rise_m"]) <= 0.25,
    }
    solid = [m for m in meshes if m["lo"] is not None and m["hi"] is not None]
    bbox_z = ([min(m["lo"][2] for m in solid), max(m["hi"][2] for m in solid)] if solid else None)
    return {"checks": checks, "measured": {"mesh_count": len(meshes), "tread_count": len(tops),
            "target_floor_rise_m": round(float(p["rise_m"]), 4),
            "mesh_z_bounds_m": [round(float(v), 4) for v in bbox_z] if bbox_z is not None else None,
            "mesh_bbox_height_m": round(height, 4),
            "mesh_bbox_definition": "Asset-local Z extent of all mesh points, including handrails; this is not the target floor rise.",
            "tread_top_z_m": [round(float(t), 4) for t in tops],
            "rises_m": [round(r, 4) for r in rises],
            "riser_count_including_target_floor_step": len(rises),
            "observed_min_riser_m": round(min(rises), 4) if rises else None,
            "observed_max_riser_m": round(max(rises), 4) if rises else None,
            "profile_riser_min_m": min_riser, "profile_riser_max_m": max_riser,
            "rises_definition": {
                "coordinates": "Asset-local Z in metres.",
                "first": "Lowest measured tread top minus the lower-floor target Z=0.",
                "between": "Differences between consecutive sorted measured tread-top Z values.",
                "last": "target_floor_rise_m minus the highest measured tread top; includes the final step to the requested upper-floor target.",
                "floor_target_limitation": "Both floor elevations are reference targets, not measured floor surfaces; this does not verify an upper slab, scene placement, floor connection or robot climbability."
            },
            "footprint_sorted_m": [round(v, 4) for v in foot],
            "traversal_points": len(points)},
            "not_verified": ["placement of the stair inside the Scenesmith room (no overlay authored into the scene)",
                             "collision against the room walls, door and furniture",
                             "multi-storey connection and acceptance gates G1-G7 (scene is a single-storey glTF export)",
                             "climbability under contact dynamics or any robot simulation"]}


TOOLS = {"room_meshes": room_meshes, "stair_candidates": stair_candidates,
         "stair_build": stair_build, "stair_check": stair_check}


def main():
    req = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    out = Path(req["out_dir"])
    if not out.is_dir() or not _inside(Path(sys.argv[1]).parent, out) or req["tool"] not in TOOLS:
        raise SystemExit(3)
    os.chdir(out)
    sys.path.insert(0, req["buildingsgen_src"])  # read-only source tree; -B keeps it free of bytecode
    try:
        result = {"ok": True, "result": TOOLS[req["tool"]](req, out)}
        code = 0
    except Exception as exc:
        result = {"ok": False, "error": type(exc).__name__ + ": " + str(exc)[:500],
                  "where": traceback.extract_tb(exc.__traceback__)[-1].name}
        code = 2
    text = json.dumps(result, indent=1, allow_nan=False, default=str)
    (out/"result.json").write_text(text, encoding="utf-8")
    raise SystemExit(code)


if __name__ == "__main__":
    main()
