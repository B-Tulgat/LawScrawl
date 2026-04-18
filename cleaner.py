import os
from pathlib import Path

def clean_law_files(input_dir, output_dir):
    input_path = Path(input_dir).expanduser()
    output_path = Path(output_dir).expanduser()

    stop_phrase = "Хүчинтэй эсэхХайлтын үр дүн"

    # Track stats for your peace of mind
    total_files = 0
    cleaned_files = 0

    for md_file in input_path.rglob("*.md"):
        total_files += 1
        try:
            with open(md_file, 'r', encoding='utf-8') as f:
                all_lines = f.readlines()

            # RULE 1: Content only starts from line 78 (Index 77)
            # If the file is shorter than 78 lines, it's likely an empty/error scrape
            if len(all_lines) < 78:
                continue

            content_after_header = all_lines[77:]

            # RULE 2: Only consider the stop phrase AFTER line 78
            final_content = []
            for line in content_after_header:
                if stop_phrase in line:
                    break
                final_content.append(line)

            # Recreate folder structure
            relative_path = md_file.relative_to(input_path)
            new_file_path = output_path / relative_path
            new_file_path.parent.mkdir(parents=True, exist_ok=True)

            with open(new_file_path, 'w', encoding='utf-8') as f:
                f.writelines(final_content)

            cleaned_files += 1

        except Exception as e:
            print(f"Error on {md_file.name}: {e}")

    print(f"✅ Done! Processed {total_files} files. Saved {cleaned_files} valid laws to {output_dir}")

# Execute
clean_law_files('~/Desktop/LawScrawl', '~/Desktop/LawScrawl_Cleaned')
