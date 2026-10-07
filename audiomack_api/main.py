import time
from fastapi import FastAPI, Query, HTTPException, Request

try:
    from app.test import extract_track_info
    from app.album import extract_album_info
except ModuleNotFoundError:
    from test import extract_track_info
    from album import extract_album_info


app = FastAPI(
    title="Audiomack API",
    version="1.0.0"
)


@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    start_time = time.perf_counter()
    response = await call_next(request)
    process_time = time.perf_counter() - start_time

    # Add execution time to response headers
    response.headers["X-Process-Time"] = f"{process_time:.4f}s"

    # Print to terminal
    print(f"⏱️  [{request.method}] {request.url.path} completed in {process_time:.3f}s")

    return response


@app.get("/")
def home():
    return {
        "success": True,
        "message": "Audiomack API is running"
    }


@app.get("/song")
def song(
    url: str = Query(
        ...,
        description="Audiomack song URL"
    )
):
    if "audiomack.com" not in url:
        raise HTTPException(
            status_code=400,
            detail="Invalid Audiomack URL"
        )

    start_time = time.perf_counter()
    try:
        result = extract_track_info(url)
        elapsed = time.perf_counter() - start_time

        return {
            "success": True,
            "execution_time": f"{elapsed:.2f}s",
            "data": result
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )


@app.get("/album")
def album(
    url: str = Query(
        ...,
        description="Audiomack album URL"
    ),
    track: int | None = Query(
        None,
        description=(
            "Optional album track number. "
            "Example: 1, 2, 3"
        )
    )
):
    if "audiomack.com" not in url:
        raise HTTPException(
            status_code=400,
            detail="Invalid Audiomack URL"
        )

    if "/album/" not in url:
        raise HTTPException(
            status_code=400,
            detail="URL must be an Audiomack album URL"
        )

    if track is not None and track < 1:
        raise HTTPException(
            status_code=400,
            detail="track must be 1 or greater"
        )

    start_time = time.perf_counter()
    try:
        result = extract_album_info(
            url,
            selected_track=track
        )
        elapsed = time.perf_counter() - start_time

        return {
            "success": True,
            "execution_time": f"{elapsed:.2f}s",
            "data": result
        }

    except ValueError as e:
        raise HTTPException(
            status_code=404,
            detail=str(e)
        )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )
