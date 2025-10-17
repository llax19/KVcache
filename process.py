import json
import os
import glob


def process_jsonl_to_custom_format(input_file, output_file):
    type_mapping = {
        "text": 1,
        "search": 2,
        "image": 3,
        "file": 4,
    }

    try:
        with open(output_file, "w", encoding="utf-8") as outfile:
            with open(input_file, "r", encoding="utf-8") as infile:
                for line in infile:
                    line = line.strip()
                    if not line:
                        continue

                    data = json.loads(line)
                    output_line = None

                    # Nested format with "block_ids"
                    if "requests" in data:
                        req_type = 1
                        for request in data.get("requests", []):
                            for turn in request.get("turns", []):
                                for llm_message in turn.get("llm_messages", []):
                                    for chunk in llm_message.get("chunks", []):
                                        block_ids = chunk.get("block_ids", [])
                                        if block_ids:
                                            ids_str = ",".join(map(str, block_ids))
                                            outfile.write(f"{{{ids_str}}} {req_type}\n")
                    else:
                        block_ids = data.get("hash_ids", [])
                        req_type = 1  # Default type

                        # Check if it's the format with a "type" field
                        if "type" in data:
                            req_type_str = data.get("type", "text")
                            req_type = type_mapping.get(req_type_str, 1)

                        if block_ids:
                            ids_str = ",".join(map(str, block_ids))
                            output_line = f"{{{ids_str}}} {req_type}\n"

                    if output_line:
                        outfile.write(output_line)

        print(f"Processed {input_file} -> {output_file}")

    except FileNotFoundError:
        print(f"Error: Input file not found {input_file}")
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSONL format in {input_file}. Details: {e}")
    except Exception as e:
        print(f"An unexpected error occurred while processing {input_file}: {e}")


if __name__ == "__main__":
    input_dir = "input_samples/raw/"
    output_dir = "input_samples/"

    if not os.path.isdir(input_dir):
        print(f"Error: Input directory not found: {input_dir}")
    else:
        jsonl_files = glob.glob(os.path.join(input_dir, "*.jsonl"))
        if not jsonl_files:
            print(f"No .jsonl files found in {input_dir}")

        for input_path in jsonl_files:
            base_name = os.path.basename(input_path)
            output_name = os.path.splitext(base_name)[0]
            output_path = os.path.join(output_dir, output_name)

            process_jsonl_to_custom_format(input_path, output_path)
