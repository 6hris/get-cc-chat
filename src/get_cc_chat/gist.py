"""GitHub Gist upload via gh CLI."""
import subprocess


def check_gh_cli() -> bool:
    """Check if the gh CLI is installed and accessible."""
    try:
        result = subprocess.run(
            ["gh", "--version"], capture_output=True, timeout=5,
        )
        return result.returncode == 0
    except FileNotFoundError:
        return False


def create_gist(html_path: str) -> str:
    """Upload an HTML file as a public GitHub Gist.

    Returns a gisthost.github.io shareable URL.
    Raises RuntimeError if the upload fails.
    """
    result = subprocess.run(
        ["gh", "gist", "create", "--public", "--filename", "index.html", html_path],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "gh gist create failed")

    gist_url = result.stdout.strip()
    gist_id = gist_url.rstrip("/").split("/")[-1]
    return f"https://gisthost.github.io/?{gist_id}"
