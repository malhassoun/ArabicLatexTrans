
   
from pylatexenc.latex2text import LatexNodes2Text
import os
import re
import json
import zipfile
import tarfile
import regex
import subprocess
import os
import requests
from bs4 import BeautifulSoup
from typing import List
import time
from src.utils.progress import st
import sys
from pathlib import Path

options = r"\[[^\[\]]*?\]"
spaces = r"[ \t]*"
get_pattern_brace = lambda index: rf"\{{((?:[^{{}}]++|(?{index}))*+)\}}"


def _is_within_dir(base_dir: Path, target_path: Path) -> bool:
    try:
        target_path.resolve().relative_to(base_dir.resolve())
        return True
    except ValueError:
        return False


def _safe_extract_zip(zip_ref: zipfile.ZipFile, extract_path: Path) -> None:
    for member in zip_ref.infolist():
        member_path = extract_path / member.filename
        if not _is_within_dir(extract_path, member_path):
            raise ValueError(f"Unsafe zip member path: {member.filename}")
    zip_ref.extractall(extract_path)


def _safe_extract_tar(tar_ref: tarfile.TarFile, extract_path: Path) -> None:
    for member in tar_ref.getmembers():
        member_path = extract_path / member.name
        if not _is_within_dir(extract_path, member_path):
            raise ValueError(f"Unsafe tar member path: {member.name}")
    tar_ref.extractall(extract_path)

def get_pattern_command_full(name, n=None):
    pattern = rf'\\({name})'
    if n is None:
        pattern += rf'{spaces}({options})?'
        n = 1
        begin_brace = 3
    else:
        begin_brace = 2
    for i in range(n):
        tmp = get_pattern_brace(i*2+begin_brace)
        pattern += rf'{spaces}({tmp})'
    if n == 0:
        pattern += r'(?=[^a-zA-Z])'
    return pattern

def extract_compressed_files(folder_path):
    """
    Traverse the given folder and extract all compressed files (zip, tar, tar.gz, etc.).
    After extraction, delete the source compressed files.
    
    Args:
        folder_path (str): Path to the folder containing compressed files.
    """
    # paths = []
    for root, _, files in os.walk(folder_path):
        for file in files:
            file_path = os.path.join(root, file)
            try:
                if zipfile.is_zipfile(file_path):
                    with zipfile.ZipFile(file_path, 'r') as zip_ref:
                        extract_path = Path(root) / file.replace('.zip', '')
                        extract_path.mkdir(parents=True, exist_ok=True)
                        _safe_extract_zip(zip_ref, extract_path)
                        print(f"Extracted {file} to {extract_path}")
                    os.remove(file_path)
                elif tarfile.is_tarfile(file_path):
                    with tarfile.open(file_path, 'r:*') as tar_ref:
                        extract_path = Path(root) / file.replace('.tar', '').replace('.gz', '')
                        extract_path.mkdir(parents=True, exist_ok=True)
                        _safe_extract_tar(tar_ref, extract_path)
                        print(f"Extracted {file} to {extract_path}")
                    os.remove(file_path)
            except Exception as e:
                print(f"[SKIP] Failed to extract {file_path}: {e}")
    # return paths

def get_profect_dirs(folder_path):
    """
    Get a list of all subdirectories in the given folder.
    
    Args:
        folder_path (str): Path to the folder.
    
    Returns:
        list: A list of subdirectory paths.
    """
    projects = []
    for d in os.listdir(folder_path):
        if os.path.isdir(os.path.join(folder_path, d)):
            project_path = os.path.join(folder_path, d)
            projects.append(project_path)
    return projects

def has_appendix(latex_code):
    appendix_pattern = re.compile(r"\\appendix\b")
    return bool(appendix_pattern.search(latex_code))

def remove_appendix_content(latex_code):
    appendix_pattern = re.compile(r"\\appendix\b.*?(?=\\end\{document\})", re.DOTALL)
    
    modified_code = appendix_pattern.sub("", latex_code)
    
    return modified_code

def extract_latex_nodes(tex):
    walker = LatexWalker(tex)
    nodes, npos, nlen = walker.get_latex_nodes()
    return nodes

def extract_text_from_tex(tex):
    # convert = CustomLatexNodes2Text()
    # text = convert.latex_to_text(tex)
    text = LatexNodes2Text().latex_to_text(tex)
    return text
    
def extract_structure(nodes, depth=0):
    structure = {
        'command': [],
        'environment': [],
        'special': [],
        'math': []
    }

    for node in nodes:
        if isinstance(node, LatexMacroNode):
            structure['command'].append({'name': node.macroname, 'depth': depth})
            if node.nodeargd:
                sub_structure = extract_structure(node.nodeargd.argnlist, depth + 1)
                for key in sub_structure:
                    structure[key].extend(sub_structure[key])
        elif isinstance(node, LatexEnvironmentNode):
            structure['environment'].append({'name': node.envname, 'depth': depth})
            sub_structure = extract_structure(node.nodelist, depth + 1)
            for key in sub_structure:
                structure[key].extend(sub_structure[key])
        elif isinstance(node, LatexGroupNode):
            sub_structure = extract_structure(node.nodelist, depth + 1)
            for key in sub_structure:
                structure[key].extend(sub_structure[key])
        elif isinstance(node, LatexSpecialsNode):
            structure['special'].append({'chars': node.specials_chars, 'depth': depth})
        elif isinstance(node, LatexMathNode):
            structure['math'].append({'type': node.displaytype, 'depth': depth})
            sub_structure = extract_structure(node.nodelist, depth + 1)
            for key in sub_structure:
                structure[key].extend(sub_structure[key])

    return structure

def extract_title(latex_code):
    title_start = latex_code.find(r"\title{")
    if title_start == -1:
        title_start = latex_code.find(r"\title[")
    if title_start == -1:
        return "No title"  
    
    brace_start = latex_code.find("{", title_start)
    if brace_start == -1:
        return "No title"  
    
    stack = []  
    for i in range(brace_start, len(latex_code)):
        if latex_code[i] == "{":
            stack.append(i)  
        elif latex_code[i] == "}":
            stack.pop()  
            if not stack:  
                return latex_code[brace_start + 1:i].strip()

    return "No title"  

def extract_abstract(latex_code):
    abstract_pattern = regex.compile(r"\\begin\{abstract\}(.*?)\\end\{abstract\}", regex.DOTALL)
    
    match = abstract_pattern.search(latex_code)
    
    if match:
        abstract = match.group(1).strip() 
        return abstract
    
    abstract_start = latex_code.find(r"\abstract{")
    if abstract_start == -1:
        return "No abstract"

    brace_start = latex_code.find("{", abstract_start)
    if brace_start == -1:
        return "No abstract"

    stack = []
    for i in range(brace_start, len(latex_code)):
        if latex_code[i] == "{":
            stack.append(i)  #
        elif latex_code[i] == "}":
            stack.pop()  # 
            if not stack:  # 
                return latex_code[brace_start + 1:i].strip()

    return "No abstract" 

def extract_keywords(latex_code):
    keywords_pattern = regex.compile(r"\\keywords\{(?:\{([^{}]*)\}|([^{}]*))\}", regex.DOTALL)
    
    match = keywords_pattern.search(latex_code)
    
    keywords = match.group(1) or match.group(2) if match else None
    return keywords.strip() if keywords else None

def extract_sections(latex_code):
    section_pattern = regex.compile(r"\\(section|chapter)\b")
    match = section_pattern.search(latex_code)
    if not match:
        return latex_code, ""
    
    section_index = match.start()
    before_section = latex_code[:section_index]
    after_section = latex_code[section_index:]
    return before_section, after_section

def extract_captions(latex_code):
    caption_start = latex_code.find(r"\caption{")
    if caption_start == -1:
        caption_start = latex_code.find(r"\caption[")
    if caption_start == -1:
        return "No caption"  
    
    brace_start = latex_code.find("{", caption_start)
    if brace_start == -1:
        return "No caption"  
    
    stack = []  
    for i in range(brace_start, len(latex_code)):
        if latex_code[i] == "{":
            stack.append(i)  
        elif latex_code[i] == "}":
            stack.pop()  
            if not stack:  
                return latex_code[brace_start + 1:i].strip()

    return "No caption"  

def replace_figures(latex_code):
    figure_pattern = regex.compile(
        r"\\begin\{(figure\*?|wrapfigure|SCfigure|tikzpicture)\}.*?\\end\{\1\}",
        regex.DOTALL
    )
    
    def replace_match(match):
        figure_code = match.group(0)  
        caption = extract_captions(figure_code)  
        return f"<FIGURE: {caption}>"
    
    latex_code = figure_pattern.sub(replace_match, latex_code)
    return latex_code

def replace_tables(latex_code):
    table_pattern = regex.compile(
        r"\\begin\{(table\*?|tabular|tabularx|longtable)\}.*?\\end\{\1\}",
        regex.DOTALL
    )
    
    def replace_match(match):
        table_code = match.group(0)  
        caption = extract_captions(table_code)  
        return f"<TABLE: {caption}>"
    
    latex_code = table_pattern.sub(replace_match, latex_code)
    return latex_code

def replace_newcommand(newcommand, latex_code):
    command_name, n_arguments, content = newcommand
    pattern = regex.compile(get_pattern_command_full(command_name, n_arguments), regex.DOTALL)

    def replace_function(match):
        this_content = content
        name = match.group(1)
        assert re.match(command_name, name)
        for i in range(n_arguments):
            text = match.group(3 + i * 2)
            this_content = this_content.replace(f'#{i+1}', f' {text} ')
        return this_content

    return pattern.sub(replace_function, latex_code)

def process_newcommands(latex_code):

    def get_nonNone(*args):
        result = [arg for arg in args if arg is not None]
        assert len(result) == 1
        return result[0]

    pattern_newcommand = rf'\\(?:newcommand\*?|def|renewcommand){spaces}(?:\{{\\([a-zA-Z]+)\}}|\\([a-zA-Z]+)){spaces}(?:\[(\d)\])?{spaces}({get_pattern_brace(4)})'  # \newcommand{name}[n_arguments]{content}, group 1/2: name, group 3: n_arguments, group 5: content

    pattern = regex.compile(pattern_newcommand, regex.DOTALL)
    count = 0
    full_newcommands = []
    match = pattern.search(latex_code)
    while match:
        name1 = match.group(1)
        name2 = match.group(2)
        name = get_nonNone(name1, name2)
        n_arguments = match.group(3)
        if n_arguments is None:
            n_arguments = 0
        else:
            n_arguments = int(n_arguments)
        content = match.group(5)
        latex_code = latex_code.replace(match.group(), f'REPLACE_{count}_NEWCOMMAND')
        # print(latex_code)
        full_newcommands.append(match.group(0))
        latex_code = replace_newcommand((name, n_arguments, content), latex_code)
        count += 1
        match = pattern.search(latex_code)
    for i in range(count):
        latex_code = latex_code.replace(f'REPLACE_{i}_NEWCOMMAND', full_newcommands[i])
    return latex_code

def replace_href(latex_code):
    href_pattern = regex.compile(r"\\href\{[^{}]*\}\{(.*?)\}")
    
    latex_code = href_pattern.sub(r"\1", latex_code)
    return latex_code

def replace_includegraphics(latex_code):
    includegraphics_pattern = regex.compile(r"\\includegraphics(?:\[[^\]]*\])?\{[^\}]*\}", regex.DOTALL)
    latex_code = includegraphics_pattern.sub("", latex_code)
    return latex_code

def process_latex_to_eva(latex_code):
    latex_code = replace_href(latex_code)
    latex_code = replace_includegraphics(latex_code)
    latex_code = process_newcommands(latex_code)
    before_section, after_section = extract_sections(latex_code)
    title = extract_title(before_section) if extract_title(before_section) else 'No title'
    abstract = extract_abstract(before_section) if extract_abstract(before_section) else 'No abstract'
    keywords = extract_keywords(before_section) if extract_keywords(before_section) else ''
    after_section = replace_figures(after_section)
    after_section = replace_tables(after_section)
    tex_to_eva = f"{title}\n\n{abstract}\n\n{keywords}\n\n{after_section}"
    return tex_to_eva

def delete_ph(text) -> str:

    pattern = r'§(\.§){0,2}'
    text = re.sub(pattern, '', text)
    placeholder_pattern = r"<.*?PLACEHOLDER.*?>"
    text = re.sub(placeholder_pattern, "", text).strip()
    text = text.replace('\n', ' ')
    
    text = re.sub(r' +', ' ', text)
    
    return text.strip()

def extract_pure_text(dir):
    main_file_path = find_main_tex_file(dir)
    if main_file_path is None:
        raise FileNotFoundError(f"File not found: {main_file_path}")
    full_latex_code = merge_tex_from_inputs(main_file_path)
    main_latex_code = process_latex_to_eva(full_latex_code)
    pure_text = extract_text_from_tex(main_latex_code)
    return pure_text

def get_texts_from_data(folder_path, output_folder):
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)
    extract_compressed_files(folder_path)
    projects = get_profect_dirs(folder_path)
    # print("projects:", projects)
    total_projects = len(projects)
    for idx, project in enumerate(projects, start=1):
        print(f"[{idx}/{total_projects}] Processing {os.path.basename(project)}")
        try:
            text = extract_pure_text(project)
            project_name = os.path.basename(project)
            output_file = os.path.join(output_folder, f"{project_name}.txt")
            with open(output_file, "w", encoding="utf-8") as f:
                f.write(text)
        except Exception as e:
            print(f"Error processing project {project}: {e}")
            continue  # 跳过出错的项目

def extract_pure_tags(dir):
    main_file_path = find_main_tex_file(dir)
    if main_file_path is None:
        raise FileNotFoundError(f"File not found: {main_file_path}")
    main_latex_code = merge_tex_from_inputs(main_file_path)
    nodes = extract_latex_nodes(main_latex_code)
    tag_structure = extract_structure(nodes)
    return tag_structure

def loop_files(dir):
    all_files = []
    for root, dirs, files in os.walk(dir):
        for file in files:
            all_files.append(os.path.join(root, file))
    return all_files

def read_tex_file(path):
    with open(path, 'r', encoding='utf-8') as f:
        latex_code = f.read()
    return latex_code

def read_json_file(path):
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    return data
    
def find_tex_files(dir):
    all_files = loop_files(dir)

    tex_files = [f for f in all_files if f.endswith('.tex')]

    return tex_files

def remove_comments(tex: str) -> str:
    """
    Remove both % line comments and \\begin{comment} ... \\end{comment} blocks from LaTeX code.
    """
    # Remove \begin{comment}...\end{comment} environments
    tex = re.sub(r'\\begin\s*\{comment\}.*?\\end\s*\{comment\}', '', tex, flags=re.DOTALL)

    lines = tex.splitlines()
    cleaned = []
    for line in lines:
        stripped_line = line.lstrip()
        # Skip full-line comments (ignoring leading whitespace)
        if re.match(r'^(?<!\\)%', stripped_line):
            continue
        # Remove inline comments (ignore escaped %)
        line = re.sub(r'(?<!\\)%.*', '', line)
        cleaned.append(line.rstrip())  # Optionally remove trailing whitespace

    return '\n'.join(cleaned)

def compress_newlines(tex):
    """
    Replace consecutive newlines (including spaces) exceeding four with exactly two newlines.

    Args:
        content (str): The input string to process.

    Returns:
        str: The processed string with normalized newlines.
    """
    return re.sub(r'(\s*\n\s*){3,}', '\n\n', tex)

def get_env_pattern(command_name):
    """
    Get the regex pattern for matching environments.
    """
    get_command_env = lambda name: rf"\\begin{spaces}\{{(?!document\b|center\b|proof\b|multicols\b)({name})\}}{spaces}({options})?(.*?)\\end{spaces}\{{\1\}}"
    command_env = get_command_env(command_name)
    env_pattern = regex.compile(command_env, regex.DOTALL)
    return env_pattern

def get_abstract_pattern():
    """
    Get the regex pattern for matching \begin{abstract} and \end{abstract} commands.
    """
    command_name = r'abstract'
    get_command_env = lambda name: rf"\\begin{spaces}\{{({name})\}}{spaces}({options})?(.*?)\\end{spaces}\{{\1\}}"
    command_abstract = get_command_env(command_name)
    abstract_pattern = regex.compile(command_abstract, regex.DOTALL)
    return abstract_pattern

def get_keywords_pattern():
    """
    Get the regex pattern for matching \keywords commands.
    """
    command_name = r'keywords'
    command = get_pattern_command_full(command_name)
    keywords_pattern = regex.compile(command, regex.DOTALL)
    return keywords_pattern

def get_section_pattern():
    """
    Get the regex pattern for matching section commands.
    """
    command_name = r'section|subsection|subsubsection' # add chapter
    command = get_pattern_command_full(command_name)
    section_pattern = regex.compile(command, regex.DOTALL)
    return section_pattern

def get_begin_document_pattern():
    """
    Get the regex pattern for matching \begin{document} command.
    """
    pattern = regex.compile(r'\\begin\s*\{\s*document\s*\}', regex.DOTALL)
    return pattern

def get_newcommand_pattern():
    """
    Get the regex pattern for matching \newcommand commands.
    """
    newcommand = rf'\\(?:newcommand\*?|def|renewcommand|newenvironment|renewenvironment){spaces}(?:\{{\\([a-zA-Z]+)\}}|\\([a-zA-Z]+)){spaces}(?:\[(\d)\])?{spaces}({get_pattern_brace(4)})'  # \newcommand{name}[n_arguments]{content}, group 1/2: name, group 3: n_arguments, group 5: content
    newcommand_pattern = regex.compile(newcommand, regex.DOTALL)
    return newcommand_pattern

def get_command_pattern(name):
    """
    Get the regex pattern for matching LaTeX commands.
    """
    command = get_pattern_command_full(name)
    command_pattern = regex.compile(command, regex.DOTALL)
    return command_pattern

def get_captionof_pattern():
    """
    Match \captionof{env}{text} structure using regex with support for nested braces.
    """
    pattern = regex.compile(r"""
        \\captionof          # match \captionof
        \s*                  # optional whitespace
        (?P<braces>          # named group 'braces' to handle nested {}
            \{               # opening {
                (?:          # non-capturing group
                    [^{}]+   # non-brace characters
                    |        # OR
                    (?&braces)  # recursive match for nested braces
                )*
            \}               # closing }
        )
        \s*                  # optional whitespace
        (?P=braces)          # repeat the same structure for the second argument
    """, regex.VERBOSE | regex.DOTALL)
    return pattern

def add_ctex_package(latex_code):

    if "\\usepackage[UTF8]{ctex}" not in latex_code:
        ctex_package = "\\usepackage[UTF8]{ctex}"
        documentclass = r'documentclass'
        documentclass_pattern = get_command_pattern(documentclass)
        # documentclass_pattern = regex.compile(command, regex.DOTALL)
        match = documentclass_pattern.search(latex_code)
        if match:
            position = match.end()
            latex_code = latex_code[:position] + "\n" + ctex_package + "\n" + latex_code[position:]
    return latex_code

def add_ja_package(latex_code):

    if "\\usepackage{luatex-ja}" not in latex_code:
        ctex_package = "\\usepackage{luatexja}"
        documentclass = r'documentclass'
        documentclass_pattern = get_command_pattern(documentclass)
        # documentclass_pattern = regex.compile(command, regex.DOTALL)
        match = documentclass_pattern.search(latex_code)
        if match:
            position = match.end()
            latex_code = latex_code[:position] + "\n" + ctex_package + "\n" + latex_code[position:]
    return latex_code
## Updated fix_table_direction_for_arabic to preserve the table structure and content without changes 
def fix_table_direction_for_arabic(latex_code):
    """
    Force LaTeX tables to render left-to-right in an Arabic document.

    The original table source is preserved. Only an English/LTR
    direction group is added around the actual tabular environment.
    """

    tabular_pattern = re.compile(
        r"""
        (?P<table>
            \\begin\s*\{
                (?P<env>
                    tabular\*?
                    |tabularx
                    |tabulary
                    |longtable\*?
                    |tblr
                )
            \}
            .*?
            \\end\s*\{\s*(?P=env)\s*\}
        )
        """,
        re.VERBOSE | re.DOTALL
    )

    def wrap(match):
        table = match.group("table")

        # Don't apply the fix twice
        if r"\begin{english}" in table:
            return table

        return (
            "\\begin{english}\n"
            + table
            + "\n\\end{english}"
        )

    return tabular_pattern.sub(wrap, latex_code)
    
def fix_figure_direction_for_arabic(latex_code):
    """
    Force every \\includegraphics call into an explicit left-to-right
    direction context, using \\beginL ... \\endL (provided by the `bidi`
    package, which polyglossia loads internally for Arabic).

    Images have no inherent text direction, but under RTL document
    direction, bidi's box-placement logic still affects how a figure's
    bounding box gets anchored within the column -- confirmed by testing:
    figures sized with \\includegraphics[width=\\textwidth]{...} inside
    figure*/figure environments were visibly clipped on the left edge of
    the page in a real compiled Arabic PDF, even though \\textwidth itself
    is a fixed length unaffected by direction. Wrapping each
    \\includegraphics call in \\beginL...\\endL forces standard, direction-
    unaffected LTR box placement, matching how the image would be placed
    in the original (non-RTL) document.
    """
    pattern = re.compile(r"\\includegraphics(\[[^\]]*\])?\{[^}]*\}")

    def wrap(match):
        return "\\beginL\n" + match.group(0) + "\n\\endL"

    return pattern.sub(wrap, latex_code)
#Detect the LaTeX template so template-specific fixes are applied safely(Updated by Imaan Alkhanen)
def detect_latex_template(latex_code: str) -> str:
    """
    Detect the LaTeX front-matter/template style.

    Returns:
        acmart
        authblk
        arxiv
        acl
        generic
    """

    if re.search(
        r"\\documentclass(?:\[[^\]]*\])?\{acmart\}",
        latex_code
    ):
        return "acmart"

    if re.search(
        r"\\usepackage(?:\[[^\]]*\])?\{authblk\}",
        latex_code
    ):
        return "authblk"

    if re.search(
        r"\\usepackage(?:\[[^\]]*\])?\{arxiv\}",
        latex_code
    ):
        return "arxiv"

    if (
        re.search(
            r"\\usepackage(?:\[[^\]]*\])?\{acl[^}]*\}",
            latex_code,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"\\documentclass(?:\[[^\]]*\])?\{acl[^}]*\}",
            latex_code,
            flags=re.IGNORECASE,
        )
    ):
        return "acl"

    return "generic"
#Preserve author structure and apply direction handling without breaking acmart metadata(Updated by Imaan Alkhanen)
def fix_author_direction_for_arabic(latex_code: str) -> str:
    """
    Fix author blocks for Arabic documents.

    - Remove blank lines inside \\author{...}.
    - For acmart: do NOT add \\LR inside \\author.
    - For other classes: wrap English author lines with \\LR{...}.
    - Preserve \\And and \\AND exactly as they appear.
    - Preserve author order and layout commands.
    """

    # acmart handles author metadata internally.
    # Putting \LR inside \author breaks its processing.
    is_acmart = bool(
        re.search(
            r"\\documentclass(?:\[[^\]]*\])?\{acmart\}",
            latex_code
        )
    )

    def find_matching_brace(text, open_pos):
        depth = 0

        for i in range(open_pos, len(text)):
            if text[i] == "{" and (i == 0 or text[i - 1] != "\\"):
                depth += 1
            elif text[i] == "}" and (i == 0 or text[i - 1] != "\\"):
                depth -= 1
                if depth == 0:
                    return i

        return None

    def clean_author_content(content):
        cleaned_lines = []

        for line in content.splitlines():
            stripped = line.strip()

            # Remove blank lines only
            if not stripped:
                continue

            # Preserve author separators exactly
            if stripped in (r"\And", r"\AND"):
                cleaned_lines.append(stripped)
                continue

            # IMPORTANT:
            # Never insert \LR inside acmart \author blocks.
            if not is_acmart and re.search(r"[A-Za-z]", stripped):
                if not stripped.startswith(r"\LR{"):

                    # Keep LaTeX line break outside \LR{...}
                    if stripped.endswith(r"\\"):
                        text = stripped[:-2].rstrip()
                        stripped = r"\LR{" + text + r"}\\"
                    else:
                        stripped = r"\LR{" + stripped + "}"

            cleaned_lines.append(stripped)

        return "\n".join(cleaned_lines)

    result = []
    pos = 0

    # Supports:
    # \author{...}
    # \author[...]{...}
    author_pattern = re.compile(
        r"\\author(?:\s*\[[^\]]*\])?\s*\{"
    )

    while True:
        match = author_pattern.search(latex_code, pos)

        if not match:
            result.append(latex_code[pos:])
            break

        open_brace = match.end() - 1
        close_brace = find_matching_brace(latex_code, open_brace)

        if close_brace is None:
            # Leave malformed block unchanged
            result.append(latex_code[pos:])
            break

        result.append(latex_code[pos:open_brace + 1])

        content = latex_code[open_brace + 1:close_brace]
        cleaned = clean_author_content(content)

        if cleaned:
            result.append("\n" + cleaned + "\n")

        result.append("}")
        pos = close_brace + 1

    return "".join(result)
# Translate the abstract heading while preserving class-specific front-matter behavior(Updated by Imaan Alkhanen)
def fix_abstract_heading_for_arabic(latex_code: str) -> str:
    """
    Translate the abstract heading while preserving template-specific
    front-matter behavior.
    """

    template = detect_latex_template(latex_code)

    # acmart collects the abstract internally.
    # Redefining the abstract environment breaks its front matter.
    if template == "acmart":
        return latex_code

    abstract_patch = (
        "\\renewenvironment{abstract}\n"
        "{\\begin{center}\\bfseries ملخص\\end{center}\\quotation}\n"
        "{\\endquotation}\n"
    )

    begin_document = re.search(
        r"\\begin\s*\{\s*document\s*\}",
        latex_code
    )

    if begin_document:
        position = begin_document.start()

        latex_code = (
            latex_code[:position]
            + abstract_patch
            + "\n"
            + latex_code[position:]
        )

    return latex_code
def fix_acmart_frontmatter_for_arabic(latex_code: str) -> str:
    """
    Restore acmart abstract and keywords when the bidi/hyperref
    maketitle path omits them.

    This fix is applied only to acmart documents.
    """

    if detect_latex_template(latex_code) != "acmart":
        return latex_code

    # Avoid applying the patch more than once.
    if "ArabicLatexTransKeywords" in latex_code:
        return latex_code

    maketitle_match = re.search(
        r"\\maketitle\b",
        latex_code
    )

    if not maketitle_match:
        return latex_code

    # Save keywords BEFORE \maketitle, because acmart may clear
    # \@keywords while processing the title.
    before_patch = (
        "\n"
        "% ArabicLatexTrans: preserve ACM front matter\n"
        "\\makeatletter\n"
        "\\let\\ArabicLatexTransKeywords\\@keywords\n"
        "\\makeatother\n"
    )

    position = maketitle_match.start()

    latex_code = (
        latex_code[:position]
        + before_patch
        + latex_code[position:]
    )

    # Find maketitle again because the previous insertion changed offsets.
    maketitle_match = re.search(
        r"\\maketitle\b",
        latex_code
    )

    if not maketitle_match:
        return latex_code

    after_patch = (
        "\n"
        "% ArabicLatexTrans: restore ACM abstract and keywords\n"
        "\\makeatletter\n"
        "\\@mkabstract\n"
        "\\begingroup\n"
        "  \\@specialsection{الكلمات المفتاحية}%\n"
        "  \\noindent\\ArabicLatexTransKeywords\\par\n"
        "\\endgroup\n"
        "\\makeatother\n"
    )

    position = maketitle_match.end()

    latex_code = (
        latex_code[:position]
        + after_patch
        + latex_code[position:]
    )

    return latex_code
def fix_pdfoutput_for_xelatex(latex_code: str) -> str:
    """
    Disable pdfLaTeX-specific \\pdfoutput=1 for XeLaTeX/LuaLaTeX.
    """
    return re.sub(
        r'(?m)^\s*\\pdfoutput\s*=\s*1\s*$',
        r'% \\pdfoutput=1  % disabled for XeLaTeX/LuaLaTeX',
        latex_code,
    )

def fix_number_direction_for_arabic(latex_code):
    """
    Force decimal numbers and percentages into an explicit left-to-right
    direction using Unicode bidi ISOLATE characters (U+2066 LEFT-TO-RIGHT
    ISOLATE / U+2069 POP DIRECTIONAL ISOLATE).

    Confirmed by direct visual inspection of a compiled PDF (Table 2's
    caption in arXiv 2106.08364): Cohen's kappa values written as "0.79"
    and "0.82" in the source render as "79.0" and "82.0" -- the digit
    groups on either side of the decimal point are swapped by RTL
    reordering.

    THIS IS A MORE CONSERVATIVE VERSION than an earlier attempt, which
    caused a severe, confirmed regression: wrapping numbers found anywhere
    in the document -- including "1.2", "1.3" style SECTION/SUBSECTION
    NUMBERS -- corrupted whatever mechanism builds running headers and
    pagination from them, producing garbled fragments on every page and
    several near-blank pages. Rather than trying to exclude every
    structural case one regression at a time (the pattern that failed
    four times before this), this version explicitly EXCLUDES the content
    of heading commands entirely (\\section, \\subsection, \\subsubsection,
    \\paragraph) -- the numbers this fix targets live in body text and
    captions, never in headings, so excluding heading content by
    construction removes an entire category of risk rather than patching
    around individual symptoms of it.

    Also fixed here: an earlier version's color-command exclusion used
    get_command_pattern(), which only captures ONE brace argument by
    design (see get_pattern_command_full's n=1 default) -- for
    \\definecolor{name}{model}{spec}, that only matched the harmless
    {name} argument, leaving {model}{spec} (where the actual numeric
    value lives, e.g. \\definecolor{Gray}{gray}{0.9}) completely
    unprotected. Confirmed by the same compile log: this exact case
    produced "Missing character" and dimension-parsing errors. Fixed by
    calling get_pattern_command_full() directly with the correct argument
    count per command, rather than the single-argument-only helper.
    """
    LRI = "\u2066"  # LEFT-TO-RIGHT ISOLATE
    PDI = "\u2069"  # POP DIRECTIONAL ISOLATE

    protected_spans = []

    # \definecolor{name}{model}{spec} -- always exactly 3 brace arguments,
    # regardless of color model (gray takes 1 number, rgb takes 3, cmyk
    # takes 4 -- all still inside that same third argument).
    definecolor_pattern = regex.compile(
        get_pattern_command_full("definecolor", 3), regex.DOTALL
    )
    for m in definecolor_pattern.finditer(latex_code):
        protected_spans.append(m.span())

    # \color{spec}, \pagecolor{spec} -- single argument, nothing follows
    # that needs to remain eligible for number-wrapping.
    for command_name in ("color", "pagecolor"):
        pat = regex.compile(get_pattern_command_full(command_name, 1), regex.DOTALL)
        for m in pat.finditer(latex_code):
            protected_spans.append(m.span())

    # \textcolor{spec}{text}, \colorbox{spec}{text} -- protect ONLY the
    # first (color-spec) argument; the second argument is real displayed
    # content that may contain genuine numbers needing protection.
    for command_name in ("textcolor", "colorbox"):
        pat = regex.compile(get_pattern_command_full(command_name, 2), regex.DOTALL)
        for m in pat.finditer(latex_code):
            protected_spans.append(m.span(1))

    # \fcolorbox{spec1}{spec2}{text} -- protect the first two (color-spec)
    # arguments; the third is real displayed content.
    fcolorbox_pattern = regex.compile(
        get_pattern_command_full("fcolorbox", 3), regex.DOTALL
    )
    for m in fcolorbox_pattern.finditer(latex_code):
        protected_spans.append((m.start(1), m.end(2)))

    # Exclude heading commands entirely -- see docstring above for why.
    for command_name in ("section", "subsection", "subsubsection", "paragraph"):
        pat = regex.compile(get_pattern_command_full(command_name), regex.DOTALL)
        for m in pat.finditer(latex_code):
            protected_spans.append(m.span())

    def is_protected(pos):
        return any(start <= pos < end for start, end in protected_spans)

    # Math mode ($...$ and \[...\]) -- \beginL/\endL-style direction
    # commands are invalid there, and Unicode isolates have not been
    # confirmed safe inside math mode either. Escaped dollar signs (\$)
    # are not treated as math delimiters.
    math_spans = []
    dollar_positions = [m.start() for m in re.finditer(r"(?<!\\)\$", latex_code)]
    for i in range(0, len(dollar_positions) - 1, 2):
        math_spans.append((dollar_positions[i], dollar_positions[i + 1] + 1))
    for m in re.finditer(r"\\\[.*?\\\]", latex_code, re.DOTALL):
        math_spans.append((m.start(), m.end()))

    def is_math(pos):
        return any(start <= pos < end for start, end in math_spans)

    # Numbers immediately followed by a letter or backslash with no space
    # (e.g. "0.5pt", "0.95\linewidth") are LaTeX dimension values, not
    # displayed text -- EXCEPT for a LaTeX-escaped percent sign (\%),
    # which is real displayed content (a bare "%" starts a LaTeX comment,
    # so a literal percent sign must be written as \%). This is matched
    # as part of the number itself, before the dimension-safety lookahead
    # runs, so it doesn't get mistaken for a dimension command. Confirmed
    # by testing on a real compiled PDF: "84.7\%" was previously excluded
    # entirely by the backslash-lookahead (intended for cases like
    # 0.95\linewidth), leaving both the number and the percent sign
    # unprotected and allowing RTL to reorder them independently,
    # producing garbled output like "7%.84".
    pattern = re.compile(r"\d+\.\d+(?:\\%|%)?(?![a-zA-Z0-9\\])")

    def wrap(match):
        if is_protected(match.start()) or is_math(match.start()):
            return match.group(0)
        return LRI + match.group(0) + PDI

    return pattern.sub(wrap, latex_code)


def apply_arabic_content_direction_fixes(latex_code):
    """
    Apply ONLY the content-level RTL-direction fixes (figures, numbers,
    author/affiliation) -- NOT the preamble (packages, fonts, float
    settings) that add_arabic_package() also injects.

    This project generates translated content across MULTIPLE separate
    files, not just the main document (tables/*.tex, texfiles/*.tex).
    add_arabic_package() only ever runs on the main file, and its preamble
    injection must not be duplicated into a file that gets \\input{}'d
    into the main document -- this function exists so the content fixes
    can still be applied to every generated file independently.

    Confirmed by testing: a reported "0.79 renders as 79.0" bug persisted
    even after fix_number_direction_for_arabic() was confirmed correct in
    isolation, because the affected text lived entirely in a separate
    texfiles/*.tex file that reconstruct.py writes to disk directly,
    never passing through add_arabic_package() (or any content fix) at
    all -- only main.tex itself was ever being processed.
    """
    latex_code = fix_figure_direction_for_arabic(latex_code)
    latex_code = fix_number_direction_for_arabic(latex_code)
    latex_code = fix_author_direction_for_arabic(latex_code)
    return latex_code


def add_arabic_package(latex_code):
    if "\\usepackage{polyglossia}" not in latex_code and "\\usepackage{babel}" not in latex_code:
        # Apply content-level fixes to the ORIGINAL document FIRST, before
        # inserting our own preamble below. This ordering is required:
        # our own preamble contains decimal numbers (\topfraction}{0.9},
        # \textfraction}{0.1}, \floatpagefraction}{0.8},
        # \bottomfraction}{0.9}) that fix_number_direction_for_arabic
        # would otherwise match and wrap in Unicode isolate characters --
        # confirmed by testing on a real compile log: with the fixes
        # running in the other order, these exact four values (0.9, 0.9,
        # 0.8, 0.1) appeared corrupted and repeating on every single page
        # of the compiled PDF, since \renewcommand{\topfraction}{0.9} is
        # not excluded by the color-command, math-mode, heading, or
        # dimension-value exclusions (the closing brace after "0.9" is
        # none of those). Running these fixes on the original content
        # only, before any of our own text is added, avoids this entirely.
        latex_code = fix_pdfoutput_for_xelatex(latex_code)
        latex_code = fix_figure_direction_for_arabic(latex_code)
        latex_code = fix_table_direction_for_arabic(latex_code)
        latex_code = fix_number_direction_for_arabic(latex_code)
        latex_code = fix_author_direction_for_arabic(latex_code)

        has_authblk = bool(
            re.search(
                r"\\usepackage(?:\[[^\]]*\])?\{authblk\}",
                latex_code
            )
        )

        authblk_patch = ""

        arabic_packages = (
            "\\usepackage{multicol}\n"
            "\\usepackage{fontspec}\n"
             "\\usepackage{titlesec}\n"
             "\\titleformat{\\section}{\\normalfont\\large\\bfseries\\raggedleft}{\\thesection}{1em}{}\n"
             "\\titleformat{\\subsection}{\\normalfont\\large\\bfseries\\raggedleft}{\\thesubsection}{1em}{}\n"
             "\\titleformat{\\subsubsection}{\\normalfont\\large\\bfseries\\raggedleft}{\\thesubsubsection}{1em}{}\n"

            "\\let\\ArabicLatexTransOriginalAuthor\\author\n"
            # Preserve the document's original footnote separator before RTL packages load.
            "\\let\\ArabicLatexTransOriginalFootnoteRule\\footnoterule\n"

            "\\usepackage{polyglossia}\n"
            "\\setmainlanguage[numerals=maghrib]{arabic}\n"
            "\\setotherlanguage{english}\n"
            "\\newfontfamily\\arabicfont[Script=Arabic,Renderer=HarfBuzz]{Amiri}\n"
            "\\newfontfamily\\arabicfonttt[Script=Arabic]{Amiri}\n"

            "\\let\\author\\ArabicLatexTransOriginalAuthor\n"
            # Restore the original separator after RTL package initialization.
            "\\AtBeginDocument{\\let\\footnoterule\\ArabicLatexTransOriginalFootnoteRule}\n"
            
            "\\let\\UseMathForPositioningText\\relax\n"
            # Relax float-placement defaults: reduces large blank gaps that can
            # appear when LaTeX defers a large figure* float (spanning both
            # columns) to a later page and has no body text left to fill the
            # remaining column space. Confirmed by testing: a real compiled
            # Arabic PDF showed a ~55%-blank page directly below a deferred
            # figure* float. \raggedbottom additionally allows columns to end
            # at different heights instead of being stretched to align, which
            # is a common secondary cause of visible blank space.
            "\\renewcommand{\\topfraction}{0.9}\n"
            "\\renewcommand{\\textfraction}{0.1}\n"
            "\\renewcommand{\\floatpagefraction}{0.8}\n"
            "\\renewcommand{\\bottomfraction}{0.9}\n"
            "\\raggedbottom\n"
            # Raise LaTeX's default per-page float limits (default topnumber=2,
            # bottomnumber=1, totalnumber=3). Documents with many competing
            # floats -- this one has 3 figure* elements plus 3 tables -- can
            # hit these limits, causing floats to "clump" together on later
            # pages while earlier pages are left under-filled with body text
            # queued up behind the float backlog. Confirmed by testing: a real
            # compiled Arabic PDF showed a large blank area on the page
            # directly following a figure, even though the body text that
            # should have followed was verified present in the source file --
            # the text was simply queued behind other floats, not missing.
            "\\setcounter{topnumber}{9}\n"
            "\\setcounter{bottomnumber}{9}\n"
            "\\setcounter{totalnumber}{9}\n"
            # stfloats specifically patches LaTeX's known bugs in how figure*/
            # table* (double-column) floats are placed in native \twocolumn
            # documents -- a separate, stricter mechanism than single-column
            # floats, which \topfraction/\bottomfraction/\totalnumber alone do
            # not fully control. This is the standard fix for large blank
            # areas following a figure*/table* in twocolumn documents.
            #"\\usepackage{stfloats}\n"
            
        )
        documentclass_pattern = get_command_pattern("documentclass")
        match = documentclass_pattern.search(latex_code)
        begin_doc_match = re.search(r"\\begin\{document\}", latex_code)

        frontmatter_match = re.search(
            r"(?m)^\s*\\(?:title|author|date)\s*(?:\[[^\]]*\])?\s*\{",
            latex_code
        )

        if frontmatter_match:
            position = frontmatter_match.start()

            latex_code = (
                latex_code[:position]
                + arabic_packages
                + "\n"
                + latex_code[position:]
            )

        elif begin_doc_match:
            position = begin_doc_match.start()

            latex_code = (
                latex_code[:position]
                + arabic_packages
                + "\n"
                + latex_code[position:]
            )
        elif match:
            # Fallback if \begin{document} isn't found (shouldn't normally
            # happen): insert right after \documentclass instead of dropping it.
            position = match.end()
            latex_code = (
                latex_code[:position]
                + "\n"
                + arabic_packages
                + latex_code[position:]
            )
        latex_code = fix_abstract_heading_for_arabic(latex_code)
        latex_code = fix_acmart_frontmatter_for_arabic(latex_code)
    return latex_code

def find_main_tex_file(dir): 
    """
    Find the main LaTeX file in the given directory.
    """
    readme_path = os.path.join(dir, '00README.json') 
    if os.path.exists(readme_path):
        config = read_json_file(readme_path)
        for source in config.get("sources", []):
            if source.get("usage") == "toplevel":
                main_file_name = source.get("filename")
                main_file_path = os.path.join(dir, main_file_name)
                return main_file_path if os.path.exists(main_file_path) else None

    tex_files = find_tex_files(dir)
    documentclass_pattern = re.compile(r"\\document(class|style)(\[.*?\])?\{.*?\}", re.DOTALL)
        
    for tex_file in tex_files:

        # Read the LaTeX code
        with open(tex_file, 'r', encoding='utf-8') as f:
            latex_code = f.read()
        latex_code = remove_comments(latex_code)    
        
        # Check if \documentclass is present
        if not documentclass_pattern.search(latex_code):
            continue

        return tex_file
    
    return None

def merge_tex_from_inputs(main_file_path):

    if main_file_path is None:
        return None
    dirname = os.path.dirname(main_file_path)
    maincontent = read_tex_file(main_file_path)
    maincontent = remove_comments(maincontent) 
    pattern_input = re.compile(r'\\(input|include){(.*?)}')
    while True:
        result = pattern_input.search(maincontent)
        if result is None:
            break
        begin, end = result.span()
        match = result.group(2)
        inputfilepath = os.path.join(dirname, match)
        if match.endswith('.tex'): #判断input的文件是否以.tex结尾
            if os.path.exists(f'{inputfilepath}'):
                inputfilepath = f'{inputfilepath}'
            else:
                raise FileNotFoundError(f"File not found: {inputfilepath}")
        else:
            if os.path.exists(f'{inputfilepath}.tex'):
                inputfilepath = f'{inputfilepath}.tex'
            else:
                raise FileNotFoundError(f"File not found: {inputfilepath}.tex")
        input_tex = read_tex_file(inputfilepath)
        input_tex = remove_comments(input_tex)
        maincontent = maincontent[:begin] + input_tex + maincontent[end:]
        # print('merging', inputfilepath)

    return maincontent

def save_to_tex(data, output_file):
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(data)

def save_to_json(data, output_file):
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def compile_with_latexmk(tex_file: str, out_dir: str = "out", engine: str = "pdflatex"):
    os.makedirs(out_dir, exist_ok=True)
    
    cmd = [
        "latexmk",
        f"-{engine}",                # 
        "-interaction=nonstopmode",   # 
        f"-outdir={out_dir}",          # 
        f"-synctex=1",
        f"-f",                 # 
        tex_file
    ]
    
    try:
        subprocess.run(cmd, check=True)
        print("✅ 编译成功！")
    except subprocess.CalledProcessError as e:
        print("❌ 编译失败！")
        print(e)

def collect_latex_errors_with_logpath(folder: str):
    """
    遍历每个项目，优先查找 build_pdflatex 目录，其次是 build 目录，
    读取其中的 .log 文件，统计 LaTeX Error 出现次数。
    仅将包含错误的项目记录到 JSON 文件中，并输出错误项目总数。
    """
    error_keyword = re.compile(r"latex error", re.IGNORECASE)
    summary = {}
    error_project_count = 0

    for project_name in os.listdir(folder):
        project_path = os.path.join(folder, project_name)
        if not os.path.isdir(project_path):
            continue

        preferred_builds = ["build_pdflatex", "build"]
        build_path = None
        for build_dir in preferred_builds:
            candidate = os.path.join(project_path, build_dir)
            if os.path.isdir(candidate):
                build_path = candidate
                break

        if build_path is None:
            continue  # 没有找到 build 目录

        log_files = [f for f in os.listdir(build_path) if f.endswith(".log")]
        if not log_files:
            continue  # 没有 log 文件

        log_path = os.path.join(build_path, log_files[0])
        try:
            with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
                error_count = len(error_keyword.findall(content))
        except Exception as e:
            print(f"Error reading {log_path}: {e}")
            continue

        if error_count > 0:
            summary[project_name] = {
                "total_errors": error_count,
                "log_path": log_path
            }
            error_project_count += 1

    # 写入 JSON 文件（仅包含有错误的项目）
    output_path = os.path.join(folder, "latex_error_summary.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print(f"Summary saved to: {output_path}")
    print(f"🔍 共有 {error_project_count} 个项目存在 LaTeX Error。")

def get_tex_url(arxiv_id: str, headers: dict) -> str:
    """
    获取 TeX 源码下载链接
    """
    abs_url = f"https://arxiv.org/abs/{arxiv_id}"
    try:
        resp = requests.get(abs_url, headers=headers, timeout=10)
        resp.raise_for_status()
    except requests.RequestException:
        return ""
    
    soup = BeautifulSoup(resp.text, "html.parser")
    link = soup.find("a", class_="abs-button download-eprint")
    if link and link.get("href"):
        return f"https://arxiv.org{link['href']}"
    return ""

def is_already_downloaded(arxiv_id: str, save_dir: str) -> bool:
    """
    检查 tar.gz 文件或已解压目录是否存在
    """
    tar_path = os.path.join(save_dir, f"{arxiv_id}.tar.gz")
    extracted_dir = os.path.join(save_dir, arxiv_id)
    return os.path.exists(tar_path) or os.path.isdir(extracted_dir)

def download_tex(arxiv_id: str, tex_url: str, save_dir: str, headers: dict):
    """
    下载 TeX 源码 .tar.gz 文件
    """
    # os.makedirs(save_dir, exist_ok=True)
    file_path = os.path.join(save_dir, f"{arxiv_id}.tar.gz")

    try:
        with requests.get(tex_url, headers=headers, stream=True, timeout=20) as r:
            r.raise_for_status()
            total_size = int(r.headers.get("Content-Length", 0))

            sys.stderr = open(os.devnull, 'w')
            st_progress = st.progress(0)
            status_text = st.empty()
            sys.stderr = sys.__stderr__

            last_report_ts = 0.0
            with open(file_path, "wb") as f:
                downloaded = 0
                for chunk in r.iter_content(8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)

                        # Update with throttling to avoid noisy terminal output.
                        if total_size > 0:
                            now = time.time()
                            if now - last_report_ts >= 0.5 or downloaded == total_size:
                                sys.stderr = open(os.devnull, 'w')
                                progress = downloaded / total_size
                                st_progress.progress(progress)
                                status_text.text(
                                    f"Downloading {arxiv_id}: {downloaded/1024/1024:.2f}MB / {total_size/1024/1024:.2f}MB"
                                )
                                sys.stderr = sys.__stderr__
                                last_report_ts = now
            
        sys.stderr = open(os.devnull, 'w')
        st.success(f"[SUCCESS] {arxiv_id} successfully downloaded to {file_path}.")
        sys.stderr = sys.__stderr__

        return os.path.join(save_dir, f"{arxiv_id}")

    except requests.RequestException as e:
        sys.stderr = open(os.devnull, 'w')
        st.error(f"[FAIL] {arxiv_id} download failed: {e}")
        sys.stderr = sys.__stderr__
        return None

def batch_download_arxiv_tex(arxiv_ids: List[str], save_dir: str = "./tex_sources"):
    """
    批量下载多个 arXiv 论文的 TeX 源码
    """
    source_dirs = []
    headers = {"User-Agent": "Mozilla/5.0"}
    for arxiv_id in arxiv_ids:
        if is_already_downloaded(arxiv_id, save_dir):
            source_dirs.append(os.path.join(save_dir, arxiv_id))
            print(f"[SkIP] Already downloaded: {arxiv_id}")
            continue

        tex_url = get_tex_url(arxiv_id, headers)
        if tex_url:
            dir = download_tex(arxiv_id, tex_url, save_dir, headers)
            if dir:
                source_dirs.append(dir)
            else:
                print(f"[SKIP] Source download failed for {arxiv_id}, skip TeX processing.")
        else:
            print(f"[SKIP] No TeX source found for {arxiv_id}. Please check the arXiv ID or the availability of the source.")

            # 下载PDF文件
        pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
        pdf_path = os.path.join(save_dir, arxiv_id, f"{arxiv_id}.pdf")
        os.makedirs(os.path.dirname(pdf_path), exist_ok=True)

        try:
            response = requests.get(pdf_url, headers=headers)
            response.raise_for_status()
            with open(pdf_path, 'wb') as f:
                f.write(response.content)
            sys.stderr = open(os.devnull, 'w')
            st.success(f"[SUCCESS] Downloaded PDF for {arxiv_id}")
            sys.stderr = sys.__stderr__
        except Exception as e:
            sys.stderr = open(os.devnull, 'w')
            st.error(f"[ERROR] Failed to download PDF for {arxiv_id}: {str(e)}")
            sys.stderr = sys.__stderr__

    return source_dirs

def get_arxiv_category(arxiv_ids: List[str]) -> dict:
    results = {}
    headers = {"User-Agent": "Mozilla/5.0"}
    for arxiv_id in arxiv_ids:
        abs_url = f"https://arxiv.org/abs/{arxiv_id}"
        categories = []

        try:
            resp = requests.get(abs_url, headers=headers, timeout=10)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

            subjects_div = soup.find("div", class_="subjects")
            if subjects_div:
                matches = re.findall(r"\(([a-z]+\.[A-Z]+)\)", subjects_div.text)
                categories.extend(matches)
            else:
                td_subjects = soup.find("td", class_="tablecell subjects")
                if td_subjects:
                    matches = re.findall(r'\(([a-z]+\.[A-Z]+)\)', td_subjects.text)
                    categories.extend(matches)

            if not categories:
                print(f"[WARNING] No categories found for {arxiv_id}")

        except requests.RequestException as e:
            print(f"[ERROR] Failed to fetch {arxiv_id}: {e}")
            categories = []

        results[arxiv_id] = (categories)
        time.sleep(1)  

    return results

def is_valid_arxiv_id(id_str):
    # 现代格式：YYYY.NNNNN 或 YYYY.NNNNNNN
    if re.match(r'^\d{4}\.\d{5,7}(?:v\d+)?$', id_str):
        return True
    # 旧格式：学科分类/YYMMNNN（如 hep-th/9901001）
    if re.match(r'^[\w\-]+/\d{7}(?:v\d+)?$', id_str):
        return True
    return False

def extract_arxiv_ids(arxiv_list):
    ids = []
    for item in arxiv_list:
        if is_valid_arxiv_id(item):
            ids.append(item)
            continue

        url_pattern = r'(?:arxiv\.org/)(?:abs|pdf|e-print)/([\w\-]+/\d{7}(?:v\d+)?|\d{4}\.\d{5,7}(?:v\d+)?)(?:\.pdf)?'
        match = re.search(url_pattern, item)
        if match:
            ids.append(match.group(1))
    return ids

def extract_arxiv_ids_V2(item):

    ids = ""
    if is_valid_arxiv_id(item):
        ids = item

    else:
        url_pattern = r'(?:arxiv\.org/)(?:abs|pdf|e-print)/([\w\-]+/\d{7}(?:v\d+)?|\d{4}\.\d{5,7}(?:v\d+)?)(?:\.pdf)?'
        match = re.search(url_pattern, item)
        if match:
            ids = match.group(1)
    return ids
            
        
