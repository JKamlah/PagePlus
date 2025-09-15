import subprocess
import sys
from pathlib import Path


def main():
    """Runs the Streamlit GUI application."""
    # Construct the path to the app.py file relative to this script
    app_path = Path(__file__).parent / "app.py"
    command = ["streamlit", "run", str(app_path)]
    try:
        subprocess.run(command, check=True)
    except FileNotFoundError:
        print(
            "Error: 'streamlit' command not found. Make sure Streamlit is installed.",
            file=sys.stderr,
        )
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        print(f"Error running Streamlit app: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
