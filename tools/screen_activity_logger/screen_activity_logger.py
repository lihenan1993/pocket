# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "mss>=10.1.0",
#     "openai>=2.0.0",
#     "Pillow>=12.0.0",
# ]
# ///
from __future__ import annotations

import argparse
import base64
import importlib
import json
import math
import time
import tomllib
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, cast

from openai import OpenAI
from PIL import Image, ImageChops

if TYPE_CHECKING:
    from types import TracebackType

    class ScreenshotFrame(Protocol):
        size: tuple[int, int]
        bgra: bytes

    class ScreenCapture(Protocol):
        monitors: list[dict[str, Any]]

        def __enter__(self) -> ScreenCapture: ...

        def __exit__(
            self,
            exc_type: type[BaseException] | None,
            exc: BaseException | None,
            traceback: TracebackType | None,
        ) -> bool | None: ...

        def grab(self, monitor: dict[str, Any]) -> ScreenshotFrame: ...


DEFAULT_CONFIG_PATH = Path("config.toml")
DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_MODEL = "qwen3.5-flash"
DEFAULT_OUTPUT_DIR = Path("activity_logs")
DEFAULT_MONITOR = "primary"
DEFAULT_COMPRESSED_MAX_EDGE = 1280
DEFAULT_COMPRESSED_JPEG_QUALITY = 70
DEFAULT_CHANGE_DETECTION_ENABLED = True
DEFAULT_CHANGE_THRESHOLD = 0.015
CHANGE_DETECTION_SAMPLE_SIZE = (96, 54)
CHANGE_DETECTION_PIXEL_THRESHOLD = 12
VALID_ACTIVITY_STATUSES = frozenset(
    (
        "\u5de5\u4f5c",
        "\u5a31\u4e50",
        "\u5b66\u4e60",
        "\u5176\u4ed6",
    )
)


@dataclass(frozen=True)
class AppConfig:
    api_key: str
    base_url: str
    model: str
    interval_seconds: float
    output_dir: Path
    monitor: str
    compressed_max_edge: int
    compressed_jpeg_quality: int
    change_detection_enabled: bool
    change_threshold: float


@dataclass(frozen=True)
class CaptureResult:
    captured_at: datetime
    original_path: Path
    compact_path: Path


@dataclass(frozen=True)
class ActivityAnalysis:
    summary: str
    status: str


@dataclass
class RuntimeState:
    previous_compact_path: Path | None = None
    previous_analysis: ActivityAnalysis | None = None
    previous_entry: dict[str, Any] | None = None


def create_screen_capture() -> ScreenCapture:
    module = importlib.import_module("mss")
    return cast("ScreenCapture", module.MSS())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Periodically capture the primary screen and log AI summaries.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help="Path to a TOML config file. Defaults to config.toml.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Capture, summarize, and write one log entry, then exit.",
    )
    parser.add_argument(
        "--dry-run-model",
        action="store_true",
        help="Skip the Bailian API call and write a mock summary.",
    )
    return parser.parse_args()


def load_config(path: Path) -> AppConfig:
    if not path.exists():
        raise FileNotFoundError(
            f"Config file not found: {path}. Copy config.example.toml to config.toml first.",
        )

    with path.open("rb") as file:
        data = tomllib.load(file)

    interval_seconds = float(data.get("interval_seconds", 60))
    if interval_seconds <= 0:
        raise ValueError("interval_seconds must be greater than 0.")

    compressed_max_edge = int(
        data.get("compressed_max_edge", DEFAULT_COMPRESSED_MAX_EDGE)
    )
    if compressed_max_edge <= 0:
        raise ValueError("compressed_max_edge must be greater than 0.")

    compressed_jpeg_quality = int(
        data.get("compressed_jpeg_quality", DEFAULT_COMPRESSED_JPEG_QUALITY),
    )
    if not 1 <= compressed_jpeg_quality <= 95:
        raise ValueError("compressed_jpeg_quality must be between 1 and 95.")

    change_detection_enabled = bool(
        data.get("change_detection_enabled", DEFAULT_CHANGE_DETECTION_ENABLED)
    )

    change_threshold = float(data.get("change_threshold", DEFAULT_CHANGE_THRESHOLD))
    if not 0 <= change_threshold <= 1:
        raise ValueError("change_threshold must be between 0 and 1.")

    output_dir = Path(str(data.get("output_dir", DEFAULT_OUTPUT_DIR)))

    return AppConfig(
        api_key=str(data.get("api_key", "")).strip(),
        base_url=str(data.get("base_url", DEFAULT_BASE_URL)).strip(),
        model=str(data.get("model", DEFAULT_MODEL)).strip(),
        interval_seconds=interval_seconds,
        output_dir=output_dir,
        monitor=str(data.get("monitor", DEFAULT_MONITOR)).strip().lower(),
        compressed_max_edge=compressed_max_edge,
        compressed_jpeg_quality=compressed_jpeg_quality,
        change_detection_enabled=change_detection_enabled,
        change_threshold=change_threshold,
    )


def capture_screen(config: AppConfig) -> CaptureResult:
    captured_at = datetime.now()
    date_part = captured_at.strftime("%Y%m%d")
    time_part = captured_at.strftime("%H%M%S")
    screenshot_dir = config.output_dir / "screenshots" / date_part
    screenshot_dir.mkdir(parents=True, exist_ok=True)

    original_path = screenshot_dir / f"{time_part}.png"
    compact_path = screenshot_dir / f"{time_part}_compact.jpg"

    with create_screen_capture() as screen_capture:
        monitor = select_monitor(screen_capture.monitors, config.monitor)
        screenshot = screen_capture.grab(monitor)
        image = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")

    image.save(original_path, format="PNG")
    compact_image = make_compact_image(image, config.compressed_max_edge)
    compact_image.save(
        compact_path,
        format="JPEG",
        quality=config.compressed_jpeg_quality,
        optimize=True,
    )

    return CaptureResult(
        captured_at=captured_at,
        original_path=original_path,
        compact_path=compact_path,
    )


def select_monitor(monitors: list[dict[str, Any]], monitor: str) -> dict[str, Any]:
    if monitor == "primary":
        return monitors[1]

    if monitor == "all":
        return monitors[0]

    try:
        monitor_index = int(monitor)
    except ValueError as exc:
        raise ValueError(
            "monitor must be 'primary', 'all', or a monitor index."
        ) from exc

    if monitor_index < 0 or monitor_index >= len(monitors):
        raise ValueError(f"monitor index must be between 0 and {len(monitors) - 1}.")

    return monitors[monitor_index]


def make_compact_image(image: Image.Image, max_edge: int) -> Image.Image:
    compact = image.copy()
    compact.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
    return compact.convert("RGB")


def calculate_change_ratio(previous_path: Path, current_path: Path) -> float:
    with Image.open(previous_path) as previous_image:
        previous = previous_image.convert("L").resize(
            CHANGE_DETECTION_SAMPLE_SIZE,
            Image.Resampling.BILINEAR,
        )

    with Image.open(current_path) as current_image:
        current = current_image.convert("L").resize(
            CHANGE_DETECTION_SAMPLE_SIZE,
            Image.Resampling.BILINEAR,
        )

    diff = ImageChops.difference(previous, current)
    histogram = diff.histogram()
    changed_pixels = sum(
        count
        for pixel_delta, count in enumerate(histogram)
        if pixel_delta >= CHANGE_DETECTION_PIXEL_THRESHOLD
    )
    total_pixels = CHANGE_DETECTION_SAMPLE_SIZE[0] * CHANGE_DETECTION_SAMPLE_SIZE[1]
    return changed_pixels / total_pixels


def should_skip_model_call(
    config: AppConfig,
    state: RuntimeState,
    compact_path: Path,
) -> tuple[bool, float | None]:
    if (
        not config.change_detection_enabled
        or state.previous_compact_path is None
        or state.previous_analysis is None
        or state.previous_entry is None
    ):
        return False, None

    change_ratio = calculate_change_ratio(state.previous_compact_path, compact_path)
    return change_ratio < config.change_threshold, change_ratio


def build_activity_prompt() -> str:
    return (
        "Analyze the screenshot. Return only compact JSON with keys "
        '"summary" and "status". '
        '"summary" must be a detailed Chinese sentence, about 20 to 60 Chinese characters, '
        "describing the visible app or webpage and the likely user activity. "
        '"status" must be exactly one of: '
        '"\u5de5\u4f5c", "\u5a31\u4e50", "\u5b66\u4e60", "\u5176\u4ed6".'
    )


def parse_activity_analysis(content: str) -> ActivityAnalysis:
    cleaned = content.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()

    json_start = cleaned.find("{")
    json_end = cleaned.rfind("}")
    if json_start != -1 and json_end != -1 and json_end > json_start:
        cleaned = cleaned[json_start : json_end + 1]

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        return ActivityAnalysis(
            summary=" ".join(content.split()), status="\u5176\u4ed6"
        )

    if not isinstance(data, dict):
        return ActivityAnalysis(
            summary=" ".join(content.split()), status="\u5176\u4ed6"
        )

    summary = str(data.get("summary", "")).strip()
    status = str(data.get("status", "\u5176\u4ed6")).strip()
    if status not in VALID_ACTIVITY_STATUSES:
        status = "\u5176\u4ed6"
    if not summary:
        summary = "\u65e0\u660e\u786e\u5c4f\u5e55\u6d3b\u52a8"

    return ActivityAnalysis(summary=summary, status=status)


def summarize_activity(
    config: AppConfig, compact_path: Path, dry_run_model: bool
) -> ActivityAnalysis:
    if dry_run_model:
        return ActivityAnalysis(
            summary="\u6b63\u5728\u8bb0\u5f55\u5c4f\u5e55\u6d3b\u52a8",
            status="\u5176\u4ed6",
        )

    if not config.api_key:
        raise ValueError("api_key is required unless --dry-run-model is used.")

    data_url = encode_image_data_url(compact_path)
    client = OpenAI(api_key=config.api_key, base_url=config.base_url)
    completion = client.chat.completions.create(
        model=config.model,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": data_url}},
                    {"type": "text", "text": build_activity_prompt()},
                ],
            },
        ],
        max_tokens=120,
        temperature=0.2,
        extra_body={"enable_thinking": False},
    )

    content = completion.choices[0].message.content
    if content is None:
        raise RuntimeError("Bailian returned an empty response.")

    return parse_activity_analysis(str(content))


def encode_image_data_url(image_path: Path) -> str:
    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


def format_log_time(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def normalize_duration_seconds(value: float) -> int | float:
    if value.is_integer():
        return int(value)
    return value


def build_log_entry(
    config: AppConfig,
    capture: CaptureResult,
    analysis: ActivityAnalysis,
    duration_seconds: int | float,
    skipped_model: bool,
    change_ratio: float | None,
) -> dict[str, Any]:
    return {
        "screenshot_time": format_log_time(capture.captured_at),
        "duration_seconds": duration_seconds,
        "screenshot": capture.compact_path.name,
        "summary": analysis.summary,
        "status": analysis.status,
        "model": config.model,
        "model_skipped": skipped_model,
        "change_ratio": change_ratio,
    }


def copy_previous_log_entry(
    previous_entry: dict[str, Any],
    capture: CaptureResult,
    change_ratio: float | None,
) -> dict[str, Any]:
    entry = previous_entry.copy()
    entry.update(
        {
            "screenshot_time": format_log_time(capture.captured_at),
            "screenshot": capture.compact_path.name,
            "model_skipped": True,
            "change_ratio": change_ratio,
        }
    )
    return entry


def append_log(
    config: AppConfig, capture: CaptureResult, entry: dict[str, Any]
) -> None:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    log_path = config.output_dir / f"{capture.captured_at:%Y%m%d}.jsonl"
    line = json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n"
    with log_path.open("a", encoding="utf-8") as file:
        file.write(line)


def next_aligned_start(now: datetime, interval_seconds: float) -> datetime:
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    seconds_since_day_start = (now - day_start).total_seconds()
    next_offset = (
        math.ceil(seconds_since_day_start / interval_seconds) * interval_seconds
    )
    return day_start + timedelta(seconds=next_offset)


def wait_for_next_aligned_start(interval_seconds: float) -> datetime:
    scheduled_time = next_aligned_start(datetime.now(), interval_seconds)
    sleep_seconds = max(0.0, (scheduled_time - datetime.now()).total_seconds())
    if sleep_seconds > 0:
        time.sleep(sleep_seconds)
    return scheduled_time


def run_once(
    config: AppConfig,
    dry_run_model: bool,
    state: RuntimeState,
    duration_seconds: int | float,
) -> None:
    capture = capture_screen(config)
    skipped_model = False
    change_ratio: float | None = None

    try:
        skipped_model, change_ratio = should_skip_model_call(
            config,
            state,
            capture.compact_path,
        )
        if skipped_model and state.previous_entry is not None:
            entry = copy_previous_log_entry(
                state.previous_entry,
                capture,
                change_ratio,
            )
        else:
            analysis = summarize_activity(config, capture.compact_path, dry_run_model)
            state.previous_analysis = analysis
            entry = build_log_entry(
                config=config,
                capture=capture,
                analysis=analysis,
                duration_seconds=duration_seconds,
                skipped_model=skipped_model,
                change_ratio=change_ratio,
            )
    except Exception as exc:
        analysis = ActivityAnalysis(
            summary=f"\u5206\u6790\u5931\u8d25\uff1a{exc}",
            status="\u5176\u4ed6",
        )
        entry = build_log_entry(
            config=config,
            capture=capture,
            analysis=analysis,
            duration_seconds=duration_seconds,
            skipped_model=skipped_model,
            change_ratio=change_ratio,
        )

    state.previous_compact_path = capture.compact_path
    state.previous_entry = entry
    append_log(config, capture, entry)
    print(json.dumps(entry, ensure_ascii=False, separators=(",", ":")))


def main() -> int:
    args = parse_args()
    config = load_config(args.config)
    state = RuntimeState()
    duration_seconds = normalize_duration_seconds(config.interval_seconds)

    try:
        while True:
            if not args.once:
                wait_for_next_aligned_start(config.interval_seconds)
            run_once(
                config=config,
                dry_run_model=args.dry_run_model,
                state=state,
                duration_seconds=duration_seconds,
            )
            if args.once:
                break
    except KeyboardInterrupt:
        print("Stopped.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
