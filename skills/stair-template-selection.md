# Skill: stair-template-selection

Version binding: this file's SHA-256 is pinned in `config/skills.json`; any edit invalidates
tasks bound to the old version until the pin is deliberately updated and re-reviewed.

## Applies to
Action `scene_stair_workflow`: choosing and building a stair ("ladder") template for one
registered room of a registered scene, on CPU only. Choosing among stair families is the only
template selection the registered tools support; no ladder-specific generator exists locally.

## Inputs
`{"skill": "stair-template-selection", "scene": <registered scene id>, "room": <registered room>,
"profile": <building profile>, "clearance_m": <0..0.5>}`. Nothing else; no paths, no commands.

## Allowed tools, in this order
1. `scene.room_meshes` — read the room's glTF floor and walls, check each collision mesh
   (non-empty, finite, watertight) and measure interior and wall height.
2. `stair.candidates` — design every family the profile allows for rise = wall height and
   compare each footprint (plus clearance on both sides) with the interior.
3. Model step (writer CLI): choose `template` from the fitting families only and give 1-6
   rationale lines citing the supplied numbers (footprint, margins, riser envelope).
4. `stair.build_usd` — author the chosen family as an OpenUSD asset with colliders.
5. `stair.check_usd` — re-open the asset and measure it independently of the build record.

Parameters for steps 2, 4 and 5 are derived by the orchestrator from earlier tool results, not
taken from the model. Every tool runs in its own owned process, writes only inside a fresh
`exec-*` directory of the task, and the research and scene trees are proven unchanged.

## Acceptance (all required)
- the selection is a fitting candidate and the rationale is supported by the numbers;
- every `stair.check_usd` check is true: re-opened by OpenUSD, Z-up metres, meshes non-empty
  and finite, every mesh a collider, tread count as designed, every rise (first and last
  included) inside the profile's riser envelope, footprint as designed, fits the room with
  clearance, traversal path reaches the rise;
- every recorded output file still has its recorded SHA-256; all external bindings pinned;
- an independent review by the other CLI passes.

## Not supported by a PASS
Placement inside the scene, collision with walls, door or furniture, multi-storey gates
G1-G7, climbability under dynamics and any robot simulation are NOT VERIFIED.

## Measurement meanings
`mesh_bbox_height_m` is the Z extent of all authored meshes, including handrails. Its
`mesh_z_bounds_m` gives absolute minimum/maximum Z. These describe the whole asset,
not the floor-to-floor walking rise, and must not be divided by the number of risers.
`target_floor_rise_m` is the requested upper-floor elevation relative to lower floor Z=0.
`tread_top_z_m` records actual tread-top elevations read from the USD. `rises_m` contains
the first rise from Z=0, differences between those measured tread tops, and the final
gap from the last tread to the target floor elevation. The final gap is a target-floor
constraint; this standalone asset does not prove an upper floor exists in the scene.
`observed_min_riser_m` and `observed_max_riser_m` are extrema of that exact `rises_m`
array. `profile_riser_min_m` and `profile_riser_max_m` are the separate allowed limits.
Compare risers with these limits. A handrail above the walking elevation can legitimately
make the mesh bounding box taller than the target floor rise.
The sum of `rises_m` equals the target by construction; that identity alone is not an
independent measurement or evidence of a valid floor connection. Actual tread geometry,
the per-rise envelope checks and the stated limits of this standalone asset still apply.

## Failure, pause and resume
- Selection rejected or checks false: rework (at most two), then NEEDS_ATTENTION.
- A tool failure or a read-only input changing: NEEDS_ATTENTION, no automatic retry.
- Engine login/quota/network/timeout: the task waits at its stage for that engine; an explicit
  `resume --engine` continues the same stage without re-running a completed execution.
