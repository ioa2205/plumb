"""Local FastAPI service: settings, contracts, jobs, and the run store."""

from backend.system_tools import exclude_working_folder

# Every Plumb process, however it was started, before it looks up any program.
exclude_working_folder()
