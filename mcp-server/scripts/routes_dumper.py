import sys
import os
from starlette.routing import Mount, Route

# Resolve mcp-server root regardless of CWD
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import app

print("--- local-mcp Starlette app Routes ---")
for route in app.routes:
    if isinstance(route, Route):
        print(f"Route: {route.path} [Methods: {route.methods}]")
    elif isinstance(route, Mount):
        print(f"Mount: {route.path} -> {route.app}")
        print(f"  --- Inner {route.path} Routes ---")
        inner_app = route.app
        try:
           for r in inner_app.routes:
               print(f"  Route: {r.path} [Methods: {r.methods if hasattr(r, 'methods') else 'All'}]")
        except AttributeError:
             print("  Could not list inner routes")

print("\n--- Testing Route Inspection Complete ---")
sys.exit(0)
