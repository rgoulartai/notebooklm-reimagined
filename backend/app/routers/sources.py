from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Form
from typing import List, Optional
from uuid import UUID
import aiofiles
import os
import tempfile

from app.models.schemas import (
    SourceResponse,
    YouTubeSourceCreate,
    URLSourceCreate,
    TextSourceCreate,
    ObsidianVaultCreate,
    ApiResponse,
)
from app.services.auth import get_current_user
from app.services.supabase_client import get_supabase_client
from app.services.gemini import gemini_service
from app.services.obsidian_parser import ObsidianParser

router = APIRouter(prefix="/notebooks/{notebook_id}/sources", tags=["sources"])


async def verify_notebook_access(notebook_id: UUID, user_id: str):
    """Verify user has access to the notebook."""
    supabase = get_supabase_client()
    result = (
        supabase.table("notebooks")
        .select("id")
        .eq("id", str(notebook_id))
        .eq("user_id", user_id)
        .single()
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Notebook not found")
    return result.data


@router.post("", response_model=ApiResponse)
async def upload_source(
    notebook_id: UUID,
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
):
    """Upload a file source (PDF, DOCX, TXT, etc.)."""
    await verify_notebook_access(notebook_id, user["id"])
    supabase = get_supabase_client()

    # Determine file type
    filename = file.filename or "unknown"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "txt"
    mime_type = file.content_type or "application/octet-stream"

    type_map = {
        "pdf": "pdf",
        "docx": "docx",
        "doc": "docx",
        "txt": "txt",
        "md": "txt",
        "html": "txt",
    }
    source_type = type_map.get(ext, "txt")

    # Read file content
    content = await file.read()
    file_size = len(content)

    # Upload to Supabase Storage
    storage_path = f"{user['id']}/{notebook_id}/{filename}"

    supabase.storage.from_("sources").upload(
        storage_path,
        content,
        {"content-type": mime_type}
    )

    # Create source record
    source_data = {
        "notebook_id": str(notebook_id),
        "type": source_type,
        "name": filename,
        "status": "processing",
        "file_path": storage_path,
        "original_filename": filename,
        "mime_type": mime_type,
        "file_size_bytes": file_size,
        "metadata": {},
    }

    result = supabase.table("sources").insert(source_data).execute()

    if not result.data:
        raise HTTPException(status_code=400, detail="Failed to create source")

    source = result.data[0]

    # Process in background - for now, just mark as ready
    # In production, this would trigger async processing
    try:
        # For text files, extract content and generate summary
        if source_type == "txt":
            text_content = content.decode("utf-8", errors="ignore")
            summary_result = await gemini_service.generate_summary(text_content[:50000])

            import json
            try:
                source_guide = json.loads(summary_result["content"])
            except:
                source_guide = {"summary": summary_result["content"]}

            supabase.table("sources").update({
                "status": "ready",
                "source_guide": source_guide,
                "token_count": summary_result["usage"]["input_tokens"],
            }).eq("id", source["id"]).execute()
        else:
            # For PDFs, mark as ready (would need PDF parsing in production)
            supabase.table("sources").update({
                "status": "ready",
            }).eq("id", source["id"]).execute()

    except Exception as e:
        supabase.table("sources").update({
            "status": "failed",
            "error_message": str(e),
        }).eq("id", source["id"]).execute()

    # Update notebook source count
    supabase.rpc("increment_source_count", {"notebook_id": str(notebook_id)}).execute()

    # Refresh source data
    result = supabase.table("sources").select("*").eq("id", source["id"]).single().execute()

    return ApiResponse(data=result.data)


@router.post("/youtube", response_model=ApiResponse)
async def add_youtube_source(
    notebook_id: UUID,
    youtube: YouTubeSourceCreate,
    user: dict = Depends(get_current_user),
):
    """Add a YouTube video as a source."""
    await verify_notebook_access(notebook_id, user["id"])
    supabase = get_supabase_client()

    # Extract video ID from URL
    url = youtube.url
    video_id = None
    if "youtube.com/watch?v=" in url:
        video_id = url.split("v=")[1].split("&")[0]
    elif "youtu.be/" in url:
        video_id = url.split("youtu.be/")[1].split("?")[0]

    name = youtube.name or f"YouTube: {video_id or url}"

    source_data = {
        "notebook_id": str(notebook_id),
        "type": "youtube",
        "name": name,
        "status": "processing",
        "metadata": {
            "url": url,
            "video_id": video_id,
        },
    }

    result = supabase.table("sources").insert(source_data).execute()

    if not result.data:
        raise HTTPException(status_code=400, detail="Failed to create source")

    # In production, this would trigger transcript extraction
    # For now, mark as ready
    supabase.table("sources").update({
        "status": "ready",
    }).eq("id", result.data[0]["id"]).execute()

    return ApiResponse(data=result.data[0])


@router.post("/url", response_model=ApiResponse)
async def add_url_source(
    notebook_id: UUID,
    url_source: URLSourceCreate,
    user: dict = Depends(get_current_user),
):
    """Add a website URL as a source."""
    await verify_notebook_access(notebook_id, user["id"])
    supabase = get_supabase_client()

    name = url_source.name or url_source.url[:100]

    source_data = {
        "notebook_id": str(notebook_id),
        "type": "url",
        "name": name,
        "status": "processing",
        "metadata": {
            "url": url_source.url,
        },
    }

    result = supabase.table("sources").insert(source_data).execute()

    if not result.data:
        raise HTTPException(status_code=400, detail="Failed to create source")

    # In production, this would trigger web scraping
    supabase.table("sources").update({
        "status": "ready",
    }).eq("id", result.data[0]["id"]).execute()

    return ApiResponse(data=result.data[0])


@router.post("/text", response_model=ApiResponse)
async def add_text_source(
    notebook_id: UUID,
    text_source: TextSourceCreate,
    user: dict = Depends(get_current_user),
):
    """Add pasted text as a source."""
    await verify_notebook_access(notebook_id, user["id"])
    supabase = get_supabase_client()

    source_data = {
        "notebook_id": str(notebook_id),
        "type": "text",
        "name": text_source.name,
        "status": "processing",
        "metadata": {
            "content": text_source.content[:100000],  # Limit content size
        },
    }

    result = supabase.table("sources").insert(source_data).execute()

    if not result.data:
        raise HTTPException(status_code=400, detail="Failed to create source")

    source = result.data[0]

    # Generate summary
    try:
        summary_result = await gemini_service.generate_summary(text_source.content[:50000])

        import json
        try:
            source_guide = json.loads(summary_result["content"])
        except:
            source_guide = {"summary": summary_result["content"]}

        supabase.table("sources").update({
            "status": "ready",
            "source_guide": source_guide,
            "token_count": summary_result["usage"]["input_tokens"],
        }).eq("id", source["id"]).execute()

    except Exception as e:
        supabase.table("sources").update({
            "status": "failed",
            "error_message": str(e),
        }).eq("id", source["id"]).execute()

    result = supabase.table("sources").select("*").eq("id", source["id"]).single().execute()

    return ApiResponse(data=result.data)


@router.post("/obsidian", response_model=ApiResponse)
async def add_obsidian_vault(
    notebook_id: UUID,
    vault: ObsidianVaultCreate,
    user: dict = Depends(get_current_user),
):
    """Add an Obsidian vault as a source."""
    await verify_notebook_access(notebook_id, user["id"])
    supabase = get_supabase_client()

    # Validate vault path
    if not os.path.exists(vault.vault_path):
        raise HTTPException(status_code=400, detail="Vault path does not exist")

    if not os.path.isdir(vault.vault_path):
        raise HTTPException(status_code=400, detail="Vault path is not a directory")

    # Parse vault
    try:
        parser = ObsidianParser(vault.vault_path)
        parsed_files = parser.parse_vault(
            max_files=vault.max_files,
            include_attachments=vault.include_attachments
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error parsing vault: {str(e)}")

    if not parsed_files:
        raise HTTPException(status_code=400, detail="No markdown files found in vault")

    # Combine all notes into a single document
    combined_content = []
    all_tags = set()

    for file_data in parsed_files:
        combined_content.append(f"# {file_data['title']}\n")
        combined_content.append(f"_From: {file_data['relative_path']}_\n\n")
        combined_content.append(file_data['content'])
        combined_content.append("\n\n---\n\n")
        all_tags.update(file_data['tags'])

    final_content = "".join(combined_content)
    content_bytes = final_content.encode('utf-8')

    # Generate a name
    vault_name = vault.name or os.path.basename(vault.vault_path)
    filename = f"{vault_name}_vault.md"

    # Upload to Supabase Storage
    storage_path = f"{user['id']}/{notebook_id}/{filename}"

    supabase.storage.from_("sources").upload(
        storage_path,
        content_bytes,
        {"content-type": "text/markdown"}
    )

    # Create source record
    source_data = {
        "notebook_id": str(notebook_id),
        "type": "obsidian",
        "name": vault_name,
        "status": "processing",
        "file_path": storage_path,
        "original_filename": filename,
        "mime_type": "text/markdown",
        "file_size_bytes": len(content_bytes),
        "metadata": {
            "vault_path": vault.vault_path,
            "file_count": len(parsed_files),
            "tags": list(all_tags),
        },
    }

    result = supabase.table("sources").insert(source_data).execute()

    if not result.data:
        raise HTTPException(status_code=400, detail="Failed to create source")

    source = result.data[0]

    # Generate summary
    try:
        summary_result = await gemini_service.generate_summary(final_content[:50000])

        import json
        try:
            source_guide = json.loads(summary_result["content"])
        except:
            source_guide = {"summary": summary_result["content"]}

        # Add vault-specific metadata to source_guide
        source_guide["vault_info"] = {
            "total_notes": len(parsed_files),
            "tags": list(all_tags)[:20],  # Limit to 20 tags
        }

        supabase.table("sources").update({
            "status": "ready",
            "source_guide": source_guide,
            "token_count": summary_result["usage"]["input_tokens"],
        }).eq("id", source["id"]).execute()

    except Exception as e:
        supabase.table("sources").update({
            "status": "failed",
            "error_message": str(e),
        }).eq("id", source["id"]).execute()

    # Update notebook source count
    supabase.rpc("increment_source_count", {"notebook_id": str(notebook_id)}).execute()

    # Refresh source data
    result = supabase.table("sources").select("*").eq("id", source["id"]).single().execute()

    return ApiResponse(data=result.data)


@router.get("", response_model=ApiResponse)
async def list_sources(
    notebook_id: UUID,
    user: dict = Depends(get_current_user),
):
    """List all sources in a notebook."""
    await verify_notebook_access(notebook_id, user["id"])
    supabase = get_supabase_client()

    result = (
        supabase.table("sources")
        .select("*")
        .eq("notebook_id", str(notebook_id))
        .order("created_at", desc=True)
        .execute()
    )

    return ApiResponse(data=result.data)


@router.get("/{source_id}", response_model=ApiResponse)
async def get_source(
    notebook_id: UUID,
    source_id: UUID,
    user: dict = Depends(get_current_user),
):
    """Get a specific source."""
    await verify_notebook_access(notebook_id, user["id"])
    supabase = get_supabase_client()

    result = (
        supabase.table("sources")
        .select("*")
        .eq("id", str(source_id))
        .eq("notebook_id", str(notebook_id))
        .single()
        .execute()
    )

    if not result.data:
        raise HTTPException(status_code=404, detail="Source not found")

    return ApiResponse(data=result.data)


@router.delete("/{source_id}", response_model=ApiResponse)
async def delete_source(
    notebook_id: UUID,
    source_id: UUID,
    user: dict = Depends(get_current_user),
):
    """Delete a source."""
    await verify_notebook_access(notebook_id, user["id"])
    supabase = get_supabase_client()

    # Get source first to check file path
    source = (
        supabase.table("sources")
        .select("*")
        .eq("id", str(source_id))
        .eq("notebook_id", str(notebook_id))
        .single()
        .execute()
    )

    if not source.data:
        raise HTTPException(status_code=404, detail="Source not found")

    # Delete from storage if file exists
    if source.data.get("file_path"):
        try:
            supabase.storage.from_("sources").remove([source.data["file_path"]])
        except:
            pass  # Ignore storage errors

    # Delete record
    supabase.table("sources").delete().eq("id", str(source_id)).execute()

    # Update notebook source count
    supabase.rpc("decrement_source_count", {"notebook_id": str(notebook_id)}).execute()

    return ApiResponse(data={"deleted": True, "id": str(source_id)})
