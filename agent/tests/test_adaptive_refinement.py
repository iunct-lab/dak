import pytest
from unittest.mock import MagicMock, patch
from dak_agent.adaptive_agent import AdaptiveAgent
from dak_agent.mode_manager import ModeManager
from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_response import LlmResponse
from google.adk.tools import FunctionTool

class TestAdaptiveAgentRefinement:
    
    @pytest.fixture(autouse=True)
    def setup(self):
        self.mock_tools = [MagicMock(spec=FunctionTool)]
        self.mock_tools[0].name = "test_tool"
        self.agent = AdaptiveAgent(
            model="gemini-2.5-flash",
            name="test_agent",
            instruction="Initial instruction",
            tools=self.mock_tools,
            disable_mode_switching=False
        )

    @patch('dak_agent.mode_manager.ModeManager.generate_mode_config')
    @pytest.mark.asyncio
    async def test_history_preserved_on_switch(self, mock_generate_config):
        """A mode switch swaps instruction/tools but leaves session history to
        the context harness (ADK compaction) instead of wiping it."""
        mock_generate_config.return_value = ("New Instruction", ["test_tool"], [])

        mock_context = MagicMock(spec=CallbackContext)
        mock_context.session = MagicMock()
        events = [MagicMock(), MagicMock()]
        mock_context.session.events = events
        mock_context.state = {}

        with patch.object(self.agent, '_extract_history_summary', return_value="Summary"):
            await self.agent._perform_mode_switch(mock_context)

        assert self.agent.instruction == "New Instruction"
        assert mock_context.session.events == events

    @pytest.mark.asyncio
    async def test_switch_mode_tool_preservation(self):
        # Ensure switch_mode is in builtin tools
        builtin_names = [t.name for t in self.agent._builtin_tools if hasattr(t, 'name')]
        # Note: In the test setup we passed a generic mock tool, so switch_mode might not be there unless we add it
        # But let's check if the logic in _perform_mode_switch preserves whatever is in _builtin_tools
        
        # Add a mock switch_mode tool to builtins
        mock_switch = MagicMock()
        mock_switch.name = "switch_mode"
        self.agent._builtin_tools.append(mock_switch)
        
        mock_context = MagicMock(spec=CallbackContext)
        mock_context.session.contents = []
        mock_context.state = {}
        
        with patch.object(self.agent, '_extract_history_summary', return_value="Summary"), \
             patch('dak_agent.mode_manager.ModeManager.generate_mode_config', return_value=("New", ["other_tool"], [])):
            
            await self.agent._perform_mode_switch(mock_context)
            
            # Check if switch_mode is in the new tools list
            new_tool_names = [t.name for t in self.agent.tools if hasattr(t, 'name')]
            assert "switch_mode" in new_tool_names
