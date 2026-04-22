from pathlib import Path
from shutil import copy2
import zipfile


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "shared" / "outputs"
DEST_ROOT = PROJECT_ROOT / "shared" / "sector_inputs_only"
ZIP_PATH = PROJECT_ROOT / "shared" / "sector_inputs_only.zip"

REQUIRED_FILES = ["market_input.csv", "actual_records.csv"]


def main():
    if not SOURCE_ROOT.exists():
        raise FileNotFoundError(f"Source folder does not exist: {SOURCE_ROOT}")

    DEST_ROOT.mkdir(parents=True, exist_ok=True)

    copied_households = []
    skipped_households = []

    for household_dir in sorted(SOURCE_ROOT.iterdir()):
        if not household_dir.is_dir():
            continue

        h_id = household_dir.name
        dest_household_dir = DEST_ROOT / h_id
        dest_household_dir.mkdir(parents=True, exist_ok=True)

        missing = []
        for filename in REQUIRED_FILES:
            src = household_dir / filename
            dst = dest_household_dir / filename

            if src.exists():
                copy2(src, dst)
            else:
                missing.append(filename)

        if missing:
            skipped_households.append((h_id, missing))
        else:
            copied_households.append(h_id)

    # Create a zip for easy sending
    if ZIP_PATH.exists():
        ZIP_PATH.unlink()

    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_path in DEST_ROOT.rglob("*"):
            if file_path.is_file():
                zf.write(file_path, file_path.relative_to(DEST_ROOT.parent))

    print(f"Done. Copied {len(copied_households)} households into:")
    print(f"  {DEST_ROOT}")
    print(f"Zip created at:")
    print(f"  {ZIP_PATH}")

    if copied_households:
        print("\nCopied households:")
        for h_id in copied_households:
            print(f"  {h_id}")

    if skipped_households:
        print("\nSkipped / incomplete households:")
        for h_id, missing in skipped_households:
            print(f"  {h_id}: missing {missing}")


if __name__ == "__main__":
    main()