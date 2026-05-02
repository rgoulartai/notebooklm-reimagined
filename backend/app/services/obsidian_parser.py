"""
Obsidian Vault Parser

Handles parsing Obsidian markdown files including:
- Wikilinks [[note]]
- Tags #tag
- YAML frontmatter
- Embedded files ![[image.png]]
"""

import os
import re
from pathlib import Path
from typing import List, Dict, Optional, Tuple
import yaml


class ObsidianParser:
    """Parser for Obsidian vault markdown files."""

    def __init__(self, vault_path: str):
        """
        Initialize the parser with a vault path.

        Args:
            vault_path: Absolute path to the Obsidian vault directory
        """
        self.vault_path = Path(vault_path)
        if not self.vault_path.exists():
            raise ValueError(f"Vault path does not exist: {vault_path}")
        if not self.vault_path.is_dir():
            raise ValueError(f"Vault path is not a directory: {vault_path}")

    def list_markdown_files(self, max_files: int = 100) -> List[Path]:
        """
        List all markdown files in the vault.

        Args:
            max_files: Maximum number of files to return

        Returns:
            List of Path objects for markdown files
        """
        md_files = []
        for root, dirs, files in os.walk(self.vault_path):
            # Skip hidden directories (like .obsidian, .trash)
            dirs[:] = [d for d in dirs if not d.startswith('.')]

            for file in files:
                if file.endswith('.md') and not file.startswith('.'):
                    md_files.append(Path(root) / file)
                    if len(md_files) >= max_files:
                        return md_files

        return md_files

    def parse_frontmatter(self, content: str) -> Tuple[Dict, str]:
        """
        Extract YAML frontmatter from markdown content.

        Args:
            content: Raw markdown content

        Returns:
            Tuple of (frontmatter_dict, content_without_frontmatter)
        """
        frontmatter = {}

        # Check if content starts with ---
        if content.startswith('---\n'):
            # Find the closing ---
            match = re.match(r'^---\n(.*?)\n---\n', content, re.DOTALL)
            if match:
                try:
                    frontmatter = yaml.safe_load(match.group(1)) or {}
                except yaml.YAMLError:
                    frontmatter = {}

                # Remove frontmatter from content
                content = content[match.end():]

        return frontmatter, content

    def parse_wikilinks(self, content: str) -> str:
        """
        Convert Obsidian wikilinks to readable text.

        [[note]] -> note
        [[note|alias]] -> alias
        [[folder/note]] -> note

        Args:
            content: Markdown content with wikilinks

        Returns:
            Content with wikilinks converted
        """
        # Pattern: [[link]] or [[link|alias]]
        def replace_wikilink(match):
            link_text = match.group(1)

            # Handle alias: [[link|alias]]
            if '|' in link_text:
                _, alias = link_text.split('|', 1)
                return alias

            # Handle folder paths: [[folder/note]]
            if '/' in link_text:
                return link_text.split('/')[-1]

            return link_text

        return re.sub(r'\[\[([^\]]+)\]\]', replace_wikilink, content)

    def parse_embeds(self, content: str) -> str:
        """
        Handle embedded files.

        ![[image.png]] -> [Embedded: image.png]
        ![[note]] -> [Embedded note]

        Args:
            content: Markdown content with embeds

        Returns:
            Content with embeds converted
        """
        def replace_embed(match):
            embed_text = match.group(1)

            # Handle alias: ![[file|alias]]
            if '|' in embed_text:
                file_path, _ = embed_text.split('|', 1)
                embed_text = file_path

            # Get filename
            if '/' in embed_text:
                filename = embed_text.split('/')[-1]
            else:
                filename = embed_text

            return f"[Embedded: {filename}]"

        return re.sub(r'!\[\[([^\]]+)\]\]', replace_embed, content)

    def extract_tags(self, content: str) -> List[str]:
        """
        Extract all hashtags from content.

        Args:
            content: Markdown content

        Returns:
            List of tags (without #)
        """
        # Pattern: #tag (word characters, hyphens, underscores)
        tags = re.findall(r'#([\w\-_]+)', content)
        return list(set(tags))  # Unique tags

    def parse_file(self, file_path: Path) -> Dict:
        """
        Parse a single markdown file.

        Args:
            file_path: Path to the markdown file

        Returns:
            Dict with parsed content and metadata
        """
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            raw_content = f.read()

        # Extract frontmatter
        frontmatter, content = self.parse_frontmatter(raw_content)

        # Extract tags before processing wikilinks
        tags = self.extract_tags(content)

        # Add tags from frontmatter
        if 'tags' in frontmatter:
            fm_tags = frontmatter['tags']
            if isinstance(fm_tags, list):
                tags.extend(fm_tags)
            elif isinstance(fm_tags, str):
                tags.extend([t.strip() for t in fm_tags.split(',')])

        # Process Obsidian syntax
        content = self.parse_wikilinks(content)
        content = self.parse_embeds(content)

        # Get relative path from vault root
        rel_path = file_path.relative_to(self.vault_path)

        # Extract title (from frontmatter or filename)
        title = frontmatter.get('title') or file_path.stem

        return {
            'file_path': str(file_path),
            'relative_path': str(rel_path),
            'title': title,
            'content': content.strip(),
            'frontmatter': frontmatter,
            'tags': list(set(tags)),  # Unique tags
            'file_size': file_path.stat().st_size,
        }

    def parse_vault(self, max_files: int = 100, include_attachments: bool = False) -> List[Dict]:
        """
        Parse all markdown files in the vault.

        Args:
            max_files: Maximum number of files to parse
            include_attachments: Whether to include attachment files

        Returns:
            List of parsed file dictionaries
        """
        md_files = self.list_markdown_files(max_files)
        parsed_files = []

        for file_path in md_files:
            try:
                parsed = self.parse_file(file_path)
                parsed_files.append(parsed)
            except Exception as e:
                # Skip files that can't be parsed
                print(f"Error parsing {file_path}: {e}")
                continue

        return parsed_files
