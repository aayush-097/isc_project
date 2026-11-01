import importlib.metadata
import platform


def installed_version(package: str) -> str:
    try:
        return importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        return "not installed"


def main() -> None:
    print(f"Python: {platform.python_version()}")
    print(f"PyTorch: {installed_version('torch')}")
    print(f"Torchvision: {installed_version('torchvision')}")
    print(f"Ultralytics: {installed_version('ultralytics')}")

    try:
        import torch
    except Exception as exc:
        print("CUDA available: no (PyTorch could not be imported)")
        print(f"PyTorch import diagnostic: {type(exc).__name__}: {exc}")
        print(
            "Check the installed PyTorch build, NVIDIA driver compatibility, "
            "and GPU availability."
        )
        return

    cuda_available = torch.cuda.is_available()
    print(f"CUDA available: {'yes' if cuda_available else 'no'}")
    print(f"CUDA version reported by PyTorch: {torch.version.cuda or 'none'}")
    if cuda_available:
        for index in range(torch.cuda.device_count()):
            print(f"GPU {index}: {torch.cuda.get_device_name(index)}")
    else:
        print("GPU: unavailable")
        print(
            "Check that an NVIDIA GPU is available, the installed PyTorch build "
            "includes CUDA, and the NVIDIA driver is compatible."
        )


if __name__ == "__main__":
    main()
