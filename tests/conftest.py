import gc
import os

import pytest


def _trim_windows_working_set() -> None:
	if os.name != "nt":
		return

	try:
		import ctypes

		handle = ctypes.windll.kernel32.GetCurrentProcess()
		ctypes.windll.psapi.EmptyWorkingSet(handle)
	except Exception:
		return


def _clear_test_process_state() -> None:
	gc.collect()

	try:
		import tracemalloc

		if tracemalloc.is_tracing():
			tracemalloc.stop()
	except Exception:
		pass

	_trim_windows_working_set()


@pytest.fixture(autouse=True)
def clear_suite_caches():
	_clear_test_process_state()
	yield
	_clear_test_process_state()
