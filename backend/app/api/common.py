from fastapi import HTTPException, status


def not_implemented(feature: str) -> None:
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail={
            "code": "not_implemented",
            "message": f"{feature} is scaffolded but not implemented in Phase 1.",
        },
    )
