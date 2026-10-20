"""Offline adapter tests; no real CLI call. Defaults to actual production adapters.
The explicit runner can select the proposed adapter module for candidate verification.
"""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid
ROOT=Path(r'E:\Github\Building-Generation-Validation');sys.path.insert(0,str(ROOT))
from researchops import adapters

class NativeStructuredTests(unittest.TestCase):
    def test_codex_malformed_item_fails_with_controlled_error(self):
        for item in (42, [], "text", None, False):
            raw=json.dumps({'type':'item.completed','item':item})
            with self.assertRaises(adapters.CallError) as failure:
                adapters.parse('codex',raw,str(uuid.uuid4()))
            self.assertEqual(failure.exception.kind,'INVALID_JSON')
            self.assertEqual(failure.exception.evidence['classification_signal'],'INVALID_ENVELOPE')

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='bgv-native-schema-');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.schema=self.root/'schema.json'
        self.schema.write_text(json.dumps({'type':'object','properties':{'verdict':{'type':'string'}},
                                         'required':['verdict'],'additionalProperties':False}),encoding='utf-8')
        self.session=str(uuid.uuid4())
        self.envelope={'type':'result','subtype':'success','is_error':False,'session_id':self.session,
                       'permission_denials':[],'num_turns':1,'result':'Workflow completed.',
                       'structured_output':{'verdict':'PASS'}}
    def parse(self,obj=None,strict=True):
        return adapters.parse('claude',json.dumps(self.envelope if obj is None else obj),self.session,expect_structured=strict)
    def test_command_passes_native_schema_without_enabling_tools(self):
        cmd=adapters.command('claude',{'claude':'claude.exe'},self.session,self.schema)
        self.assertEqual(json.loads(cmd[cmd.index('--json-schema')+1]),json.loads(self.schema.read_text()))
        self.assertEqual(cmd[cmd.index('--tools')+1],'')
        self.assertIn('--safe-mode',cmd);self.assertIn('--strict-mcp-config',cmd)
        self.assertEqual(cmd[cmd.index('--mcp-config')+1],'{"mcpServers":{}}')
        self.assertNotIn('--allowedTools',cmd);self.assertNotIn('--dangerously-skip-permissions',cmd)
    def test_prefers_native_object_over_prose_result(self):
        self.assertEqual(self.parse()[0],{'verdict':'PASS'})
    def test_native_schema_value_is_not_json_loaded_twice(self):
        self.envelope['result']='not json {broken'
        self.assertEqual(self.parse()[0],{'verdict':'PASS'})
    def test_null_native_output_cannot_fallback_to_text(self):
        self.envelope.update(structured_output=None,result='{"verdict":"PASS"}')
        with self.assertRaises(adapters.CallError):self.parse()
    def test_wrong_native_type_cannot_fallback_to_text(self):
        for value in ('{"verdict":"PASS"}',[],42,False):
            self.envelope.update(structured_output=value,result='{"verdict":"PASS"}')
            with self.assertRaises(adapters.CallError):self.parse()
    def test_missing_native_output_even_success_valid_result_fails_strict(self):
        del self.envelope['structured_output'];self.envelope['result']='{"verdict":"PASS"}'
        with self.assertRaises(adapters.CallError):self.parse()
    def test_legacy_non_native_parse_can_still_read_exact_json(self):
        del self.envelope['structured_output'];self.envelope['result']='{"verdict":"PASS"}'
        self.assertEqual(self.parse(strict=False)[0],{'verdict':'PASS'})
    def test_legacy_exact_fence_accepts_but_surrounding_prose_rejects(self):
        del self.envelope['structured_output'];self.envelope['result']='\n```json\n{"verdict":"PASS"}\n```\n'
        self.assertEqual(self.parse(strict=False)[0],{'verdict':'PASS'})
        self.envelope['result']='Review follows: ```json\n{"verdict":"PASS"}\n```'
        with self.assertRaises(ValueError):self.parse(strict=False)
    def test_native_does_not_bypass_session_identity(self):
        self.envelope['session_id']=str(uuid.uuid4())
        with self.assertRaises(adapters.CallError) as failure:self.parse()
        self.assertEqual(failure.exception.kind,'SESSION_MISMATCH')
    def test_native_does_not_bypass_permission_denials(self):
        self.envelope['permission_denials']=[{'tool_name':'Bash'}]
        with self.assertRaises(adapters.CallError) as failure:self.parse()
        self.assertEqual(failure.exception.kind,'TOOL_ATTEMPT')
    def test_native_does_not_bypass_service_error(self):
        self.envelope.update(is_error=True,result='usage limit reached')
        with self.assertRaises(adapters.CallError) as failure:self.parse()
        self.assertEqual(failure.exception.kind,'QUOTA')
    def test_structured_retry_error_is_not_success(self):
        self.envelope.update(subtype='error_max_structured_output_retries',is_error=False)
        with self.assertRaises(adapters.CallError) as failure:self.parse()
        self.assertEqual(failure.exception.kind,'INVALID_JSON')
    def test_envelope_wrong_type_fails_controlled(self):
        with self.assertRaises(adapters.CallError):self.parse([])
    def test_invoke_requires_native_channel_and_preserves_safe_evidence(self):
        policy={'timeout_seconds':5,'memory_mb':256}
        with patch.object(adapters.winproc,'run_owned',return_value=(0,json.dumps(self.envelope),'',0.01)):
            value,evidence=adapters.invoke('claude',{'claude':'cli.exe'},policy,'safe literal prompt',
                self.schema,self.root,lambda *a:None,self.session)
        self.assertEqual(value,{'verdict':'PASS'});self.assertEqual(evidence['session_id'],self.session)
        self.assertTrue(evidence['tools_disabled'])
    def test_invalid_raw_native_response_not_persisted(self):
        marker='FAKE-SECRET-'+uuid.uuid4().hex
        self.envelope.update(structured_output=None,result=marker)
        with patch.object(adapters.winproc,'run_owned',return_value=(0,json.dumps(self.envelope),'',0.01)):
            with self.assertRaises(adapters.CallError) as failure:
                adapters.invoke('claude',{'claude':'cli.exe'},{'timeout_seconds':5,'memory_mb':256},
                    'safe prompt',self.schema,self.root,lambda *a:None,self.session)
        self.assertNotIn(marker,json.dumps(failure.exception.evidence))
        self.assertFalse(any(marker.encode() in p.read_bytes() for p in self.root.rglob('*') if p.is_file()))

    def test_old_error_keywords_do_not_classify_incidental_content(self):
        negative = ["Schema validation failed: unknown property credit_count",
                    "Invalid structured field credit", "Expected 429 bytes but read 400 bytes",
                    "Invalid actor count 1429", "Object 4012 has no collision mesh",
                    "The report discusses quota exceeded messages", "quota field is missing",
                    "rate limit field must be an integer", "login field is required",
                    "authentication field is unknown", "The text quotes HTTP 429 responses",
                    "Missing network field", "DNS label contains invalid character",
                    "The output should mention connection failures without diagnosing this service"]
        for message in negative:
            with self.subTest(message=message):self.assertEqual(adapters.classify(message),'CLI')

    def test_preserves_explicit_provider_auth_quota_network_signals(self):
        expected={'401 Unauthorized':'AUTH','quota exceeded':'QUOTA','DNS connection failed':'NETWORK',
                  'API Error: 429 rate limited':'QUOTA','HTTP status 401 unauthorized':'AUTH',
                  "You’ve hit your limit · resets 11pm":'QUOTA',
                  'Credit balance is too low to access the Anthropic API':'QUOTA',
                  'HTTP 503 service unavailable':'NETWORK'}
        for message,kind in expected.items():
            with self.subTest(message=message):self.assertEqual(adapters.classify(message),kind)

    def test_structured_provider_error_type_has_strong_signal(self):
        self.envelope.update(is_error=True,error={'type':'rate_limit_error','message':'unrelated 429th field'})
        with self.assertRaises(adapters.CallError) as failed:self.parse()
        self.assertEqual(failed.exception.kind,'QUOTA')
        self.assertEqual(failed.exception.evidence['classification_signal'],'PROVIDER_QUOTA_TYPE')
        self.assertEqual(failed.exception.evidence['error_source'],'CLAUDE_ERROR')

    def test_real_session_limit_envelope_is_quota_even_with_success_subtype(self):
        self.envelope.update(subtype='success', is_error=True,
            result="You've hit your session limit · resets 10:20am (Asia/Kuala_Lumpur)")
        with self.assertRaises(adapters.CallError) as failed:
            self.parse()
        self.assertEqual(failed.exception.kind, 'QUOTA')
        self.assertEqual(failed.exception.evidence['classification_signal'], 'EXPLICIT_QUOTA')
        policy = {'timeout_seconds': 5, 'memory_mb': 256}
        with patch.object(adapters.winproc, 'run_owned', return_value=(1, json.dumps(self.envelope), '', 1.5)):
            with self.assertRaises(adapters.CallError) as failed:
                adapters.invoke('claude', {'claude': 'cli.exe'}, policy, 'safe diagnostic', self.schema,
                                self.root, lambda *a: None, self.session)
        self.assertEqual(failed.exception.kind, 'QUOTA')

    def test_successful_content_quoting_a_session_limit_is_not_a_service_failure(self):
        self.envelope.update(is_error=False,
            result="You've hit your session limit · resets 10:20am (Asia/Kuala_Lumpur)",
            structured_output={'verdict': 'PASS'})
        value, _ = self.parse()
        self.assertEqual(value, {'verdict': 'PASS'})

    def test_structured_http_status_is_not_a_substring(self):
        self.envelope.update(is_error=True,status_code=429,result='Request refused')
        with self.assertRaises(adapters.CallError) as failed:self.parse()
        self.assertEqual(failed.exception.kind,'QUOTA')
        self.assertEqual(failed.exception.evidence['http_status'],429)
        self.envelope['status_code']=1429
        with self.assertRaises(adapters.CallError) as failed:self.parse()
        self.assertEqual(failed.exception.kind,'CLI')

    def test_true_error_with_schema_credit_field_is_cli_unknown_not_quota(self):
        self.envelope.update(is_error=True,error={'type':'invalid_request_error','status_code':400,
                                                'message':'Schema validation failed: credit_count field invalid'})
        with self.assertRaises(adapters.CallError) as failed:self.parse()
        self.assertEqual(failed.exception.kind,'CLI')
        self.assertEqual(failed.exception.evidence['classification_signal'],'AMBIGUOUS_CLI')

    def test_success_native_content_can_discuss_quota_without_becoming_quota(self):
        self.envelope.update(result='quota exceeded',structured_output={'verdict':'REWORK','issues':['credit_count schema invalid; HTTP 429 is quoted evidence']})
        value,more=self.parse()
        self.assertEqual(value['verdict'],'REWORK')
        self.assertFalse(more['envelope_is_error'])
        self.assertEqual(more['structured_output_type'],'OBJECT')

    def test_string_false_error_flag_is_invalid_protocol_not_quota(self):
        self.envelope.update(is_error='false',result='quota exceeded')
        with self.assertRaises(adapters.CallError) as failed:self.parse()
        self.assertEqual(failed.exception.kind,'INVALID_JSON')
        self.assertEqual(failed.exception.evidence['classification_signal'],'INVALID_ENVELOPE')

    def test_process_nonzero_does_not_scan_successful_result_payload(self):
        self.envelope.update(result='quota exceeded',structured_output={'credit':429})
        kind,details=adapters.process_failure(json.dumps(self.envelope),'Failed to save a local cache file')
        self.assertEqual(kind,'CLI');self.assertEqual(details['error_source'],'PROCESS_STDERR')

    def test_process_nonzero_uses_actual_error_envelope(self):
        self.envelope.update(is_error=True,result='API Error: 429 rate limit reached')
        kind,details=adapters.process_failure(json.dumps(self.envelope),'')
        self.assertEqual(kind,'QUOTA');self.assertEqual(details['http_status'],429)

    def test_process_local_schema_error_not_misclassified_from_words(self):
        kind,details=adapters.process_failure('',"Invalid JSON schema: credit field expected 429 bytes")
        self.assertEqual(kind,'CLI');self.assertEqual(details['classification_signal'],'AMBIGUOUS_CLI')

    def test_error_metadata_only_accepts_finite_enums_not_arbitrary_strings_or_keys(self):
        marker='FAKE-SECRET-'+uuid.uuid4().hex
        value=adapters.safe_evidence({'error_source':marker,'classification_signal':marker,
             'result_type':marker,'structured_output_type':marker,'http_status':1429,
             'envelope_is_error':False,'structured_output_present':True,'invented_model_key':marker})
        self.assertEqual(value,{'envelope_is_error':False,'structured_output_present':True})
        self.assertNotIn(marker,json.dumps(value))
        allowed=adapters.safe_evidence({'error_source':'CLAUDE_ERROR','classification_signal':'HTTP_429',
             'result_type':'STRING','structured_output_type':'MISSING','http_status':429})
        self.assertEqual(allowed['http_status'],429)

    def test_invoke_nonzero_local_failure_retains_safe_diagnostics_without_raw(self):
        self.envelope.update(result='credit words and 429 bytes',structured_output={'verdict':'PASS'})
        with patch.object(adapters.winproc,'run_owned',return_value=(1,json.dumps(self.envelope),'Local cache file write failed',0.01)):
            with self.assertRaises(adapters.CallError) as failed:
                adapters.invoke('claude',{'claude':'cli.exe'},{'timeout_seconds':5,'memory_mb':256},
                    'safe prompt',self.schema,self.root,lambda *a:None,self.session)
        self.assertEqual(failed.exception.kind,'CLI')
        self.assertEqual(failed.exception.evidence['error_source'],'PROCESS_STDERR')
        self.assertEqual(failed.exception.evidence['result_type'],'STRING')
        self.assertNotIn('credit words',json.dumps(failed.exception.evidence))


    def test_codex_nonzero_jsonl_429_from_known_error_event(self):
        stdout='\n'.join(json.dumps(event) for event in [
            {'type':'thread.started','thread_id':self.session},
            {'type':'error','message':'API Error: 429 Too Many Requests'},
            {'type':'turn.failed','error':{'message':'rate limit exceeded'}}])
        kind,details=adapters.process_failure(stdout,'')
        self.assertEqual(kind,'QUOTA');self.assertEqual(details['error_source'],'CODEX_ERROR')
        self.assertEqual(details['http_status'],429)

    def test_codex_nonzero_jsonl_401_from_failure_object(self):
        stdout='\n'.join(json.dumps(event) for event in [
            {'type':'thread.started','thread_id':self.session},
            {'type':'turn.failed','error':{'http_status_code':401,'message':'Service refused request'}}])
        kind,details=adapters.process_failure(stdout,'')
        self.assertEqual(kind,'AUTH');self.assertEqual(details['http_status'],401)

    def test_codex_nonzero_jsonl_transport_failure_from_error_event(self):
        stdout='\n'.join(json.dumps(event) for event in [
            {'type':'thread.started','thread_id':self.session},
            {'type':'error','message':'DNS connection failed'}])
        kind,details=adapters.process_failure(stdout,'')
        self.assertEqual(kind,'NETWORK');self.assertEqual(details['error_source'],'CODEX_ERROR')

    def test_codex_nonzero_does_not_scan_agent_message_or_reasoning(self):
        stdout='\n'.join(json.dumps(event) for event in [
            {'type':'thread.started','thread_id':self.session},
            {'type':'item.completed','item':{'type':'reasoning','text':'quota exceeded; HTTP429'}},
            {'type':'item.completed','item':{'type':'agent_message','text':'quota exceeded; API Error: 429'}},
            {'type':'turn.completed'}])
        kind,details=adapters.process_failure(stdout,'Local cache write failed')
        self.assertEqual(kind,'CLI');self.assertEqual(details['error_source'],'PROCESS_STDERR')

    def test_codex_classify_single_error_event_extracts_message(self):
        self.assertEqual(adapters.classify(json.dumps({'type':'error','message':'API Error: 429 rate limit reached'})),'QUOTA')
        self.assertEqual(adapters.classify(json.dumps({'type':'turn.failed','error':{'message':'401 Unauthorized'}})),'AUTH')

    def test_codex_parse_known_error_keeps_finite_diagnostic(self):
        raw='\n'.join(json.dumps(event) for event in [
            {'type':'thread.started','thread_id':self.session},
            {'type':'error','message':'API Error: 429 Too Many Requests'}])
        with self.assertRaises(adapters.CallError) as failed:adapters.parse('codex',raw,self.session)
        self.assertEqual(failed.exception.kind,'QUOTA')
        self.assertEqual(failed.exception.evidence['error_source'],'CODEX_ERROR')

    def test_nonfatal_code_mode_notice_does_not_mask_true_jsonl_failure(self):
        stdout='\n'.join(json.dumps(event) for event in [
            {'type':'item.completed','item':{'type':'error','message':adapters.CODE_MODE_DISABLED_NOTICE}},
            {'type':'turn.failed','error':{'type':'rate_limit_error','message':'Request refused'}}])
        kind,details=adapters.process_failure(stdout,'')
        self.assertEqual(kind,'QUOTA');self.assertEqual(details['classification_signal'],'PROVIDER_QUOTA_TYPE')

    def test_explicit_extra_usage_service_message_and_quoted_negative(self):
        self.assertEqual(adapters.classify("You're out of extra usage"),'QUOTA')
        self.assertEqual(adapters.classify('The artifact quotes "You are out of extra usage"'),'CLI')


if __name__=='__main__':unittest.main(verbosity=2)
