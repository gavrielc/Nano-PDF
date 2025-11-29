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
            generated_image = ai_utils.generate_edited_slide(
                target_image=target_image,
                style_reference_images=style_images,
                full_text_context=full_text,
                user_prompt=prompt_text,
                resolution=resolution,
                enable_search=not disable_google_search
            )
            
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
    after_page: int = typer.Argument(..., help="Insert after this page number (0 for beginning)"),
    prompt: str = typer.Argument(..., help="Description of the new slide to create"),
    style_refs: Optional[str] = typer.Option(None, help="Comma-separated list of reference page numbers for style (e.g. '1,2'). Defaults to first page."),
    use_context: bool = typer.Option(True, help="Include full PDF text as context (enabled by default for better slide generation)"),
    output: Optional[str] = typer.Option(None, help="Output path for the PDF. Defaults to 'edited_<filename>'"),
    resolution: str = typer.Option("4K", help="Image resolution: '4K', '2K', '1K' (higher = better quality but slower)"),
    disable_google_search: bool = typer.Option(False, help="Disable Google Search (enabled by default)")
):
    """
    Add a new slide to a PDF using AI generation.
    Usage: nano-pdf add deck.pdf 0 "Title slide with 'Welcome to Q3 Review'"
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

    # Validate after_page
    total_pages = pdf_utils.get_page_count(str(input_path))
    if after_page < 0 or after_page > total_pages:
        typer.echo(f"Error: after_page must be between 0 and {total_pages}. Use 0 to insert at the beginning.")
        raise typer.Exit(code=1)

    typer.echo(f"Adding new slide to {pdf_path} after page {after_page}...")

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

    # Generate the new slide
    typer.echo("Generating new slide with AI...")
    try:
        generated_image = ai_utils.generate_new_slide(
            style_reference_images=style_images,
            user_prompt=prompt,
            full_text_context=full_text,
            resolution=resolution,
            enable_search=not disable_google_search
        )
    except Exception as e:
        typer.echo(f"Error generating slide: {e}")
        raise typer.Exit(code=1)

    # Re-hydrate to PDF
    typer.echo("Converting to PDF with text layer...")
    temp_pdf_file = tempfile.NamedTemporaryFile(mode='wb', suffix='.pdf', delete=False)
    temp_pdf = temp_pdf_file.name
    temp_pdf_file.close()

    try:
        pdf_utils.rehydrate_image_to_pdf(generated_image, temp_pdf)

        # Insert into the PDF
        typer.echo("Inserting slide into PDF...")
        pdf_utils.insert_page(str(input_path), temp_pdf, after_page, output)
    except Exception as e:
        typer.echo(f"Error creating PDF: {e}")
        raise typer.Exit(code=1)
    finally:
        # Cleanup
        if Path(temp_pdf).exists():
            Path(temp_pdf).unlink()

    typer.echo(f"Done! New slide added after page {after_page}. Saved to {output}")

@app.command()
def version():
    """
    Show version.
    """
    typer.echo("Nano PDF v0.1.0")

if __name__ == "__main__":
    app()
