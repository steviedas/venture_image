from importlib.metadata import PackageNotFoundError, version


def get_version() -> str:
    try:
        return version("venture-image")
    except PackageNotFoundError:
        # Fallback during editable/dev runs
        return "0.1.0"
