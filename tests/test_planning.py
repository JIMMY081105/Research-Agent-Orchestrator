"""A coordinator cannot turn free-form goals into executable commands or invented evidence."""
import copy
import unittest
import uuid

from researchops.planning import expand_proposal, validate_request
from researchops.core import expected


class ProposalTests(unittest.TestCase):
    def setUp(self):
        self.ids = [str(uuid.uuid4()) for _ in range(3)]
        self.request = {"goal_id": str(uuid.uuid4()), "prompt": "Compute the sum and sorted list of the provided numbers.",
                        "inputs": {"sample": {"kind": "numbers", "value": [2, 3, 7]},
                                   "notes": {"kind": "text", "value": "The upper floor connection was not evaluated."}}}
        self.task = {"id": self.ids[0], "action": "analyze_numbers", "input_id": "sample", "question": "", "depends_on": []}
        self.value = {"binding_sha256": "b"*64, "status": "PLANNED", "issues": [], "tasks": [self.task]}

    def expand(self, value=None):
        return expand_proposal(value or self.value, "b"*64, self.request, self.ids,
                               ["analyze_numbers", "analyze_text"], expected)

    def test_fixed_material_is_used_without_model_replacement(self):
        plan = self.expand()
        self.assertEqual(plan[0]["input"], [2, 3, 7])
        self.assertEqual(plan[0]["depends_on"], [])

    def test_shell_action_or_extra_command_cannot_be_approved(self):
        for mutation in (lambda t:t.update(action="bash"), lambda t:t.update(command="delete")):
            value = copy.deepcopy(self.value)
            mutation(value["tasks"][0])
            with self.assertRaises(ValueError): self.expand(value)

    def test_unknown_input_id_cannot_read_a_path(self):
        self.task["input_id"] = "C:/Users/User/.claude/auth.json"
        with self.assertRaises(ValueError): self.expand()

    def test_cannot_substitute_text_as_measured_numbers(self):
        self.task["input_id"] = "notes"
        with self.assertRaises(ValueError): self.expand()

    def test_blocked_plan_does_not_dispatch_partial_work(self):
        self.value.update(status="NEEDS_TOOL", issues=["No registered factory-generation adapter"])
        with self.assertRaises(ValueError): self.expand()
        self.value["tasks"] = []
        self.assertEqual(self.expand(), [])

    def test_duplicate_task_ids_are_rejected(self):
        self.value["tasks"].append(copy.deepcopy(self.task))
        with self.assertRaises(ValueError): self.expand()

    def test_dependency_cycle_and_foreign_id_are_rejected(self):
        self.task["depends_on"] = [self.ids[0]]
        with self.assertRaises(ValueError): self.expand()
        self.task["depends_on"] = [str(uuid.uuid4())]
        with self.assertRaises(ValueError): self.expand()

    def test_dependency_uses_only_approved_task_ids(self):
        second = {**self.task, "id": self.ids[1], "depends_on": [self.ids[0]]}
        self.value["tasks"].append(second)
        self.assertEqual(self.expand()[1]["depends_on"], [self.ids[0]])

    def test_wrong_binding_and_unresolved_issues_refused(self):
        self.value["binding_sha256"] = "c"*64
        with self.assertRaises(ValueError): self.expand()
        self.value["binding_sha256"] = "b"*64
        self.value["issues"] = ["Unresolved scientific question"]
        with self.assertRaises(ValueError): self.expand()

    def test_request_rejects_commands_and_bad_numeric_types(self):
        validate_request(self.request)
        self.request["shell"] = "anything"
        with self.assertRaises(ValueError): validate_request(self.request)
        del self.request["shell"]
        self.request["inputs"]["sample"]["value"] = [True]
        with self.assertRaises(ValueError): validate_request(self.request)

    def test_text_analysis_preserves_literal_source_and_generated_question(self):
        self.task.update(action="analyze_text", input_id="notes", question="Was the connection evaluated?")
        self.assertEqual(self.expand()[0]["input"], {"text": self.request["inputs"]["notes"]["value"],
                                                  "question": "Was the connection evaluated?"})
