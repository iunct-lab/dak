import os
from pathlib import Path
from typing import List, Optional, Dict, Callable
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.prompt import Prompt
from rich.markdown import Markdown
from .client import AgentClient
from .config import ConfigManager

class CommandContext:
    def __init__(self, client: AgentClient, console: Console, config: ConfigManager):
        self.client = client
        self.console = console
        self.config = config

CommandHandler = Callable[[CommandContext, List[str]], None]

class CommandRegistry:
    def __init__(self):
        self.commands: Dict[str, Dict[str, any]] = {}

    def register(self, name: str, description: str, handler: CommandHandler):
        self.commands[name] = {
            "description": description,
            "handler": handler
        }

    def get_command(self, name: str) -> Optional[CommandHandler]:
        cmd = self.commands.get(name)
        return cmd["handler"] if cmd else None

    def get_all_commands(self) -> Dict[str, str]:
        return {name: cmd["description"] for name, cmd in self.commands.items()}

    def dispatch(self, name: str, args: List[str], ctx: CommandContext):
        handler = self.get_command(name)
        if handler:
            handler(ctx, args)
        else:
            ctx.console.print(f"[yellow]Unknown command: {name}[/yellow]")

# Global registry
registry = CommandRegistry()

def load_markdown_commands(ctx: CommandContext):
    """Load custom commands from markdown files."""
    # Search paths: ~/.dak/commands and ./.dak/commands
    paths = [
        Path.home() / ".dak" / "commands",
        Path.cwd() / ".dak" / "commands"
    ]

    for path in paths:
        if not path.exists():
            continue
        
        for md_file in path.glob("*.md"):
            try:
                command_name = f"/{md_file.stem}"
                content = md_file.read_text(encoding="utf-8")
                
                # Simple frontmatter parsing
                description = "Custom command"
                prompt_content = content
                
                if content.startswith("---"):
                    parts = content.split("---", 2)
                    if len(parts) >= 3:
                        # Parse frontmatter (very basic)
                        frontmatter = parts[1]
                        prompt_content = parts[2].strip()
                        
                        for line in frontmatter.splitlines():
                            if line.strip().startswith("description:"):
                                description = line.split(":", 1)[1].strip()
                
                # Define handler closure
                def create_handler(prompt: str):
                    def handler(context: CommandContext, args: List[str]):
                        # Simple argument substitution if needed, e.g. {{args}}
                        final_prompt = prompt
                        if args:
                            arg_str = " ".join(args)
                            final_prompt = final_prompt.replace("{{args}}", arg_str)
                        
                        with context.console.status("[bold green]Executing custom command..."):
                            response_data = context.client.run_task(final_prompt, permissions={"default": "ask"})
                            
                        # Simple handling for custom commands - just show response for now
                        # Ideally this should also support the approval loop, but for MVP we'll just show text
                        # If it needs approval, it will show the "I need approval..." message
                        response_text = response_data.get("response", "")
                        context.console.print(Markdown(response_text))
                        context.console.print()
                    return handler

                registry.register(command_name, description, create_handler(prompt_content))
                
            except Exception as e:
                ctx.console.print(f"[red]Error loading command {md_file}: {e}[/red]")

# --- Standard Commands ---

def list_sessions(ctx: CommandContext, args: List[str] = None):
    """List all chat sessions and return them."""
    try:
        with ctx.console.status("[bold green]Fetching sessions..."):
            data = ctx.client.list_sessions()
        
        sessions = data.get("sessions", [])
        if not sessions:
            ctx.console.print("[yellow]No sessions found.[/yellow]")
            return None

        table = Table(title="Chat Sessions")
        table.add_column("#", style="dim")
        table.add_column("Session ID", style="cyan")
        table.add_column("Last Message", style="white")
        table.add_column("Messages", style="magenta")

        for idx, s in enumerate(sessions, 1):
            table.add_row(
                str(idx),
                s["session_id"],
                s["last_message"],
                str(s.get("message_count", "N/A"))
            )
        
        ctx.console.print(table)
        return sessions
    except Exception as e:
        ctx.console.print(f"[red]Error fetching history:[/red] {e}")
        return None

def resume_session(ctx: CommandContext, args: List[str] = None):
    """Resume a specific session, interactively if no ID provided."""
    session_id = None
    if args and len(args) > 0:
        session_id = args[0]
    
    if not session_id:
        sessions = list_sessions(ctx)
        if not sessions:
            return

        while True:
            selection = Prompt.ask("Select session # to resume (or 'q' to cancel)")
            if selection.lower() == 'q':
                return
            
            try:
                idx = int(selection)
                if 1 <= idx <= len(sessions):
                    session_id = sessions[idx-1]["session_id"]
                    break
                else:
                    ctx.console.print("[red]Invalid selection.[/red]")
            except ValueError:
                ctx.console.print("[red]Please enter a number.[/red]")

    if session_id:
        ctx.client.session_id = session_id
        ctx.console.print(f"[green]Resumed session:[/green] [bold]{session_id}[/bold]")

def show_session_history(ctx: CommandContext, session_id: str):
    """Show details of a specific chat session."""
    try:
        with ctx.console.status(f"[bold green]Fetching session {session_id}..."):
            data = ctx.client.get_session_history(session_id)
        
        messages = data.get("messages", [])
        if not messages:
            ctx.console.print(f"[yellow]No messages found for session {session_id}.[/yellow]")
            return

        ctx.console.print(Panel(f"Session: [bold]{session_id}[/bold]", style="blue"))
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            color = "green" if role == "user" else "blue"
            ctx.console.print(f"[{color}][bold]{role.upper()}:[/bold] {content}[/{color}]")
            ctx.console.print()

    except Exception as e:
        ctx.console.print(f"[red]Error:[/red] {e}")

def delete_session(ctx: CommandContext, session_id: str, confirm: bool = True):
    """Delete a specific chat session."""
    try:
        if confirm:
            pass # Assumed handled by caller

        with ctx.console.status(f"[bold red]Deleting session {session_id}..."):
            ctx.client.delete_session(session_id)
        ctx.console.print(f"[green]Session {session_id} deleted successfully.[/green]")
    except Exception as e:
        ctx.console.print(f"[red]Error:[/red] {e}")

def show_help(ctx: CommandContext, args: List[str] = None):
    """Show available commands."""
    table = Table(title="Available Commands")
    table.add_column("Command", style="cyan")
    table.add_column("Description", style="white")
    
    # Get all commands from registry
    commands = registry.get_all_commands()
    
    for cmd, desc in commands.items():
        table.add_row(cmd, desc)
    
    ctx.console.print(table)

def clear_screen(ctx: CommandContext, args: List[str] = None):
    ctx.console.clear()
    ctx.client.reset_session()
    
    user = ctx.config.get_user()
    ctx.console.print(Panel(
        f"Welcome to DAK CLI Chat, [bold]{user}[/bold]!\n"
        f"Session ID: [bold cyan]{ctx.client.session_id}[/bold cyan]\n"
        "Type '/help' for commands, or 'exit' to quit.", 
        title="DAK Chat", 
        border_style="green"
    ))

def show_current_session(ctx: CommandContext, args: List[str] = None):
    ctx.console.print(f"[blue]Current Session ID:[/blue] [bold]{ctx.client.session_id}[/bold]")

def exit_chat(ctx: CommandContext, args: List[str] = None):
    raise KeyboardInterrupt

# Register standard commands
registry.register("/help", "Show this help message", show_help)
registry.register("/history", "List chat history sessions", list_sessions)
registry.register("/resume", "Resume a session (interactive if no ID)", resume_session)
registry.register("/clear", "Clear the screen", clear_screen)
registry.register("/exit", "Exit the chat", exit_chat)
registry.register("/quit", "Exit the chat", exit_chat)
registry.register("/session", "Show current session ID", show_current_session)
