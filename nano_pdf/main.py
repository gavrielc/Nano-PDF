import typer
from typing import List, Optional
from pathlib import Path
from nano_pdf import pdf_utils, ai_utils
import concurrent.futures
import tempfile

app = typer.Typer()

@app.command()
def edit(
    pdf_path: str = typer.Argument(..., help="Path to the PDF file"),
    edits: List[str] = typer.Argument(..., help="Pairs of 'PageNumber Prompt' (e.g. 1 'Fix typo' 2 'Make blue')"),
    style_refs: Optional[str] = typer.Option(None, help="Comma-separated list of extra reference page numbers (e.g. '5,6')"),
    use_context: bool = typer.Option(False, help="Include full PDF text as context (can confuse the model)"),
    output: Optional[str] = typer.Option(None, help="Output path for the edited PDF. Defaults to 'edited_<filename>'"),
    resolution: str = typer.Option("4K", help="Image resolution: '4K', '2K', '1K' (higher = better quality but slower)"),
    disable_google_search: bool = typer.Option(False, help="Disable Google Search (enabled by default)")
):
    """
    Edit a PDF page using Nano Banana (Gemini 3 Pro Image).
    Usage: python -m src.main edit deck.pdf 1 "prompt A" 2 "prompt B"
    """
    # Check system dependencies first
    try:
        pdf_utils.check_system_dependencies()
    except RuntimeError as e:
        typer.echo(f"Error: {e}")
        raise typer.Exit(code=1)

    input_path = Path(pdf_path)
    if not input_path.exists():
        typer.echo(f"Error: File {pdf_path} not found.")
        raise typer.Exit(code=1)

    if not output:
        output = f"edited_{input_path.name}"
    
    # Parse Edits
    if len(edits) % 2 != 0:
        typer.echo("Error: Edits must be pairs of 'PageNumber Prompt'.")
        raise typer.Exit(code=1)

    # Merge duplicate page edits into a single prompt
    edits_by_page = {}
    for i in range(0, len(edits), 2):
        try:
            p_num = int(edits[i])
            prompt = edits[i+1]
            if p_num in edits_by_page:
                # Merge prompts with separator
                edits_by_page[p_num] += f"\n\nALSO: {prompt}"
            else:
                edits_by_page[p_num] = prompt
        except ValueError:
            typer.echo(f"Error: Invalid page number '{edits[i]}'")
            raise typer.Exit(code=1)

    parsed_edits = list(edits_by_page.items())

    # Validate page numbers are within range
    total_pages = pdf_utils.get_page_count(str(input_path))
    invalid_pages = [p for p, _ in parsed_edits if p < 1 or p > total_pages]
    if invalid_pages:
        typer.echo(f"Error: Invalid page number(s) {invalid_pages}. PDF has {total_pages} pages.")
        raise typer.Exit(code=1)

    typer.echo(f"Processing {pdf_path} with {len(parsed_edits)} edits...")
    
    # 1. Extract Full Text Context (Once)
    full_text = ""
    if use_context:
        typer.echo("Extracting text context...")
        full_text = pdf_utils.extract_full_text(str(input_path))
        if not full_text:
            typer.echo("Warning: Could not extract text from PDF. Context will be limited.")
    else:
        typer.echo("Skipping text context (use --use-context to enable)...")
    
    # 2. Prepare Visual Context (Style Anchors)
    typer.echo("Rendering reference images...")
    style_images = []
    
    # Add user-defined style refs
    if style_refs:
        for ref_page in style_refs.split(','):
            try:
                p_num = int(ref_page.strip())
                style_images.append(pdf_utils.render_page_as_image(str(input_path), p_num))
            except ValueError:
                typer.echo(f"Warning: Invalid style ref '{ref_page}'")
            except Exception as e:
                typer.echo(f"Warning: Could not render Page {ref_page}: {e}")

    # 3. Process Each Edit (Parallel)
    replacements = {} # page_num -> temp_pdf_path
    temp_files = []

    def process_single_page(page_num: int, prompt_text: str):
        typer.echo(f"Starting Page {page_num}...")
        try:
            target_image = pdf_utils.render_page_as_image(str(input_path), page_num)
            
            # Generate
            generated_image, response_text = ai_utils.generate_edited_slide(
                target_image=target_image,
                style_reference_images=style_images,
                full_text_context=full_text,
                user_prompt=prompt_text,
                resolution=resolution,
                enable_search=not disable_google_search
            )

            # Print model's text response if any
            if response_text:
                typer.echo(f"Model response for page {page_num}: {response_text}")

            # Re-hydrate
            temp_pdf_file = tempfile.NamedTemporaryFile(mode='wb', suffix='.pdf', delete=False)
            temp_pdf = temp_pdf_file.name
            temp_pdf_file.close()
            pdf_utils.rehydrate_image_to_pdf(generated_image, temp_pdf)
            
            typer.echo(f"Finished Page {page_num}")
            return (page_num, temp_pdf)
        except Exception as e:
            typer.echo(f"Error processing Page {page_num}: {e}")
            return None

    typer.echo(f"Processing {len(parsed_edits)} pages in parallel...")

    completed_count = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(process_single_page, p, prompt) for p, prompt in parsed_edits]

        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            if result:
                p_num, temp_pdf = result
                replacements[p_num] = temp_pdf
                temp_files.append(temp_pdf)
            completed_count += 1
            typer.echo(f"Progress: {completed_count}/{len(parsed_edits)} pages completed")

    if not replacements:
        typer.echo("No pages were successfully processed.")
        raise typer.Exit(code=1)

    # 4. Batch Stitch
    typer.echo(f"\nStitching {len(replacements)} pages into final PDF...")
    try:
        pdf_utils.batch_replace_pages(str(input_path), replacements, output)
    except Exception as e:
        typer.echo(f"Error stitching PDF: {e}")
        raise typer.Exit(code=1)
    finally:
        # Cleanup
        for f in temp_files:
            if Path(f).exists():
                Path(f).unlink()

    typer.echo(f"Done! Saved to {output}")

@app.command()
def add(
    pdf_path: str = typer.Argument(..., help="Path to the PDF file"),
    adds: List[str] = typer.Argument(..., help="Pairs of 'AfterPage Prompt' (e.g. 0 'Title slide' 2 'Summary slide')"),
    style_refs: Optional[str] = typer.Option(None, help="Comma-separated list of reference page numbers for style (e.g. '1,2'). Defaults to first page."),
    use_context: bool = typer.Option(True, help="Include full PDF text as context (enabled by default for better slide generation)"),
    output: Optional[str] = typer.Option(None, help="Output path for the PDF. Defaults to 'edited_<filename>'"),
    resolution: str = typer.Option("4K", help="Image resolution: '4K', '2K', '1K' (higher = better quality but slower)"),
    disable_google_search: bool = typer.Option(False, help="Disable Google Search (enabled by default)")
):
    """
    Add new slide(s) to a PDF using AI generation.
    Usage: nano-pdf add deck.pdf 0 "Title slide" 2 "Summary slide"
    """
    # Check system dependencies first
    try:
        pdf_utils.check_system_dependencies()
    except RuntimeError as e:
        typer.echo(f"Error: {e}")
        raise typer.Exit(code=1)

    input_path = Path(pdf_path)
    if not input_path.exists():
        typer.echo(f"Error: File {pdf_path} not found.")
        raise typer.Exit(code=1)

    if not output:
        output = f"edited_{input_path.name}"

    # Parse Adds
    if len(adds) % 2 != 0:
        typer.echo("Error: Adds must be pairs of 'AfterPage Prompt'.")
        raise typer.Exit(code=1)

    parsed_adds = []
    for i in range(0, len(adds), 2):
        try:
            after_page = int(adds[i])
            prompt = adds[i+1]
            parsed_adds.append((after_page, prompt))
        except ValueError:
            typer.echo(f"Error: Invalid page number '{adds[i]}'")
            raise typer.Exit(code=1)

    # Validate after_page values
    # Sort by after_page to validate sequentially (pages added earlier increase the valid range for later ones)
    total_pages = pdf_utils.get_page_count(str(input_path))
    sorted_adds = sorted(parsed_adds, key=lambda x: x[0])

    for idx, (after_page, _) in enumerate(sorted_adds):
        # Each previously added page increases the max valid position by 1
        max_valid_position = total_pages + idx
        if after_page < 0 or after_page > max_valid_position:
            typer.echo(f"Error: Invalid after_page value {after_page}. Must be between 0 and {max_valid_position} (considering {idx} page(s) added before it).")
            raise typer.Exit(code=1)

    # Use sorted order for processing
    parsed_adds = sorted_adds

    typer.echo(f"Adding {len(parsed_adds)} new slide(s) to {pdf_path}...")

    # Extract text context
    full_text = ""
    if use_context:
        typer.echo("Extracting text context...")
        full_text = pdf_utils.extract_full_text(str(input_path))
        if not full_text:
            typer.echo("Warning: Could not extract text from PDF. Context will be limited.")

    # Prepare style references
    typer.echo("Rendering style reference images...")
    style_images = []

    if style_refs:
        for ref_page in style_refs.split(','):
            try:
                p_num = int(ref_page.strip())
                if p_num < 1 or p_num > total_pages:
                    typer.echo(f"Warning: Style ref page {p_num} out of range, skipping")
                    continue
                style_images.append(pdf_utils.render_page_as_image(str(input_path), p_num))
            except ValueError:
                typer.echo(f"Warning: Invalid style ref '{ref_page}'")
            except Exception as e:
                typer.echo(f"Warning: Could not render Page {ref_page}: {e}")
    else:
        # Default to first page as style reference
        typer.echo("Using page 1 as default style reference...")
        try:
            style_images.append(pdf_utils.render_page_as_image(str(input_path), 1))
        except Exception as e:
            typer.echo(f"Warning: Could not render Page 1: {e}")

    # Generate new slides (Parallel)
    typer.echo(f"Generating {len(parsed_adds)} slide(s) with AI in parallel...")
    generated_slides = {}  # after_page -> temp_pdf_path
    temp_files = []

    def process_single_slide(after_page: int, prompt_text: str):
        typer.echo(f"Starting slide for insertion after page {after_page}...")
        try:
            generated_image, response_text = ai_utils.generate_new_slide(
                style_reference_images=style_images,
                user_prompt=prompt_text,
                full_text_context=full_text,
                resolution=resolution,
                enable_search=not disable_google_search
            )

            # Print model's text response if any
            if response_text:
                typer.echo(f"Model response for slide after page {after_page}: {response_text}")

            # Re-hydrate to PDF
            temp_pdf_file = tempfile.NamedTemporaryFile(mode='wb', suffix='.pdf', delete=False)
            temp_pdf = temp_pdf_file.name
            temp_pdf_file.close()
            pdf_utils.rehydrate_image_to_pdf(generated_image, temp_pdf)

            typer.echo(f"Finished slide for insertion after page {after_page}")
            return (after_page, temp_pdf)
        except Exception as e:
            typer.echo(f"Error generating slide for insertion after page {after_page}: {e}")
            return None

    completed_count = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        futures = [executor.submit(process_single_slide, after_page, prompt) for after_page, prompt in parsed_adds]

        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            if result:
                after_page, temp_pdf = result
                generated_slides[after_page] = temp_pdf
                temp_files.append(temp_pdf)
            completed_count += 1
            typer.echo(f"Progress: {completed_count}/{len(parsed_adds)} slides completed")

    if not generated_slides:
        typer.echo("No slides were successfully generated.")
        raise typer.Exit(code=1)

    # Insert all slides into the PDF
    typer.echo(f"\nInserting {len(generated_slides)} slide(s) into PDF...")
    try:
        # Sort by after_page in ASCENDING order for sequential additions
        # Each insertion increases the page count, allowing the next sequential position to exist
        sorted_adds = sorted(generated_slides.items(), key=lambda x: x[0], reverse=False)

        current_pdf = str(input_path)
        for i, (after_page, temp_pdf) in enumerate(sorted_adds):
            if i == len(sorted_adds) - 1:
                # Last insertion, write to final output
                pdf_utils.insert_page(current_pdf, temp_pdf, after_page, output)
            else:
                # Intermediate insertion, write to temp file
                temp_intermediate = tempfile.NamedTemporaryFile(mode='wb', suffix='.pdf', delete=False)
                intermediate_path = temp_intermediate.name
                temp_intermediate.close()
                temp_files.append(intermediate_path)

                pdf_utils.insert_page(current_pdf, temp_pdf, after_page, intermediate_path)
                current_pdf = intermediate_path
    except Exception as e:
        typer.echo(f"Error inserting slides: {e}")
        raise typer.Exit(code=1)
    finally:
        # Cleanup
        for f in temp_files:
            if Path(f).exists():
                Path(f).unlink()

    typer.echo(f"Done! Added {len(generated_slides)} new slide(s). Saved to {output}")

@app.command()
def version():
    """
    Show version.
    """
    typer.echo("Nano PDF v0.2.1")

if __name__ == "__main__":
    app()
