"""Separate all-mesh bounding box, requested floor rise and measured-derived risers."""
import json
import os
from pathlib import Path
import shutil
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
from researchops import scene_runner as runner

ROOT=Path(__file__).resolve().parents[1]

class StairMeasurementSemanticsTests(unittest.TestCase):
    def setUp(self):
        boundary=ROOT/'.runtime/test-measurement-semantics';boundary.mkdir(parents=True,exist_ok=True)
        self.boundary=boundary.resolve();self.base=Path(tempfile.mkdtemp(prefix='case-',dir=boundary))
        (self.base/'traversal_path.json').write_text(json.dumps({'points_m':[[0,0,0],[1,1,3.2]]}))
        self.params={'profile':'school','rise_m':3.2,'room_interior_m':[5,6],'clearance_m':0.1,'family':'u_shaped','expected_tread_count':19,'expected_footprint_m':[2.85,4.54]}
        self.tops=[round(.16*i,4) for i in range(1,20)]
        self.profile=SimpleNamespace(stair=SimpleNamespace(min_riser_m=.15,max_riser_m=.175))
    def tearDown(self):
        target=self.base.resolve()
        if self.boundary not in target.parents:raise RuntimeError('Refusing unowned test cleanup')
        shutil.rmtree(target)
    def check(self,tops=None,target=None,handrail_top=3.62):
        from pxr import UsdGeom
        tops=self.tops if tops is None else tops
        meshes=[{'path':'/Stair/Treads/tread_000','points':8,'indices':24,'finite':True,'collider':True,'lo':[0,0,.10],'hi':[1,1,.16]},
                {'path':'/Stair/Handrail/rail_042','points':8,'indices':24,'finite':True,'collider':True,'lo':[0,0,.50],'hi':[1,1,handrail_top]}]
        params={**self.params,**({'rise_m':target} if target is not None else {})}
        req={'params':params,'inputs':{'stair_usda':str(self.base/'stair.usda')}}
        with patch.object(runner,'_profile',return_value=self.profile),patch.object(runner,'measure_stair',return_value=(object(),meshes,tops,[2.85,4.54],handrail_top-.1)),patch.object(UsdGeom,'GetStageUpAxis',return_value='Z'),patch.object(UsdGeom,'GetStageMetersPerUnit',return_value=1.0):
            return runner.stair_check(req,self.base)
    def test_bbox_floor_target_profile_limits_and_observed_risers_are_separate(self):
        result=self.check();m=result['measured']
        self.assertTrue(all(result['checks'].values()))
        self.assertNotIn('height_m',m);self.assertNotIn('min_riser_m',m);self.assertNotIn('max_riser_m',m)
        self.assertEqual(3.2,m['target_floor_rise_m'])
        self.assertEqual([.1,3.62],m['mesh_z_bounds_m']);self.assertEqual(3.52,m['mesh_bbox_height_m'])
        self.assertNotEqual(m['mesh_bbox_height_m'],m['target_floor_rise_m'])
        self.assertEqual(self.tops,m['tread_top_z_m']);self.assertEqual(3.04,m['tread_top_z_m'][-1])
        self.assertEqual(20,m['riser_count_including_target_floor_step']);self.assertEqual([.16]*20,m['rises_m'])
        self.assertEqual((.16,.16),(m['observed_min_riser_m'],m['observed_max_riser_m']))
        self.assertEqual((.15,.175),(m['profile_riser_min_m'],m['profile_riser_max_m']))
        self.assertIn('requested upper-floor target',m['rises_definition']['last'])
        self.assertIn('not measured floor surfaces',m['rises_definition']['floor_target_limitation'])
        self.assertEqual(4,len(result['not_verified']))
    def test_observed_extrema_follow_tread_geometry_not_profile_limits(self):
        tops=list(self.tops);tops[1]=.26
        result=self.check(tops=tops);m=result['measured']
        self.assertEqual((.1,.22),(m['observed_min_riser_m'],m['observed_max_riser_m']))
        self.assertEqual((.15,.175),(m['profile_riser_min_m'],m['profile_riser_max_m']))
        self.assertFalse(result['checks']['every_rise_within_envelope'])
    def test_final_step_to_target_floor_is_included_and_can_fail(self):
        result=self.check(target=3.14);m=result['measured']
        self.assertEqual(.1,m['rises_m'][-1]);self.assertEqual(.1,m['observed_min_riser_m'])
        self.assertLess(m['rises_m'][-1],m['profile_riser_min_m'])
        self.assertFalse(result['checks']['every_rise_within_envelope']);self.assertFalse(result['checks']['first_and_last_rise_within_envelope'])
    def test_handrail_height_changes_bbox_but_not_tread_rises(self):
        a=self.check()['measured'];b=self.check(handrail_top=3.8)['measured']
        self.assertEqual(3.7,b['mesh_bbox_height_m']);self.assertEqual([.1,3.8],b['mesh_z_bounds_m'])
        for key in ('target_floor_rise_m','tread_top_z_m','rises_m','observed_min_riser_m','observed_max_riser_m'):
            self.assertEqual(a[key],b[key],key)
    def test_missing_treads_report_no_observed_risers_and_fail(self):
        result=self.check(tops=[]);m=result['measured']
        self.assertEqual([],m['rises_m']);self.assertIsNone(m['observed_min_riser_m']);self.assertIsNone(m['observed_max_riser_m'])
        self.assertFalse(result['checks']['every_rise_within_envelope']);self.assertFalse(result['checks']['tread_count_matches_family'])
