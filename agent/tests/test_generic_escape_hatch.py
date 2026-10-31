import unittest
from unittest.mock import MagicMock, patch
from dak_agent.mode_manager import ModeManager

class TestGenericEscapeHatch(unittest.TestCase):

    def setUp(self):
        self.mode_manager = ModeManager(model_name="test-model")

    @patch("dak_agent.mode_manager.meta_llm.complete_json")
    def test_generic_instruction_injection(self, mock_complete_json):
        # Create mock tools
        tools = []

        t1 = MagicMock()
        t1.name = "read_file"
        t1.description = "Read a file"
        tools.append(t1)

        mock_complete_json.return_value = {
            "instruction": "New instruction",
            "selected_tools": ["read_file"],
        }

        # Call generate_mode_config
        self.mode_manager.generate_mode_config(
            history_summary="Test summary",
            available_tools=tools,
            available_skills=[],
        )

        # Verify that the prompt sent to the LLM contains the generic instruction
        prompt_sent = mock_complete_json.call_args.args[1]

        # Check for key phrases in the prompt
        self.assertIn("If the user requests an action that requires tools you do not currently have", prompt_sent)
        self.assertIn("MUST follow this 2-step process", prompt_sent)
        self.assertIn("Call `list_skills`", prompt_sent)
        self.assertNotIn("request_tool_list", prompt_sent)  # switch_mode has no such parameter

        # Verify NO specific categories are mentioned
        self.assertNotIn("Capability Summary", prompt_sent)
        self.assertNotIn("File System", prompt_sent)

    @patch("dak_agent.mode_manager.meta_llm.complete_json")
    def test_empty_meta_response_falls_back(self, mock_complete_json):
        mock_complete_json.return_value = {}

        instruction, tools, skills = self.mode_manager.generate_mode_config(
            history_summary="Test summary",
            available_tools=[],
            available_skills=[],
        )

        self.assertEqual(instruction, "Continue with current task.")
        self.assertEqual(tools, [])
        self.assertEqual(skills, [])

if __name__ == '__main__':
    unittest.main()
