"""How the suite reads the `Dockerfile`, in one place.

Two modules assert over the machinery `Dockerfile` and they assert different
things about it. `tests/unit/test_release_stage.py` asserts that no instruction
in it migrates (AD-22); `tests/unit/test_payload_properties.py` asserts the
FR-38/FR-39 payload properties -- no configuration file copied, a numeric
non-root `USER`, `HOME` under a temporary directory, no `VOLUME` outside one.
Both need the same fact first: what the file's *instructions* are, as opposed to
what its lines are.

That is not the same question, and the gap between the two is where an
instruction escapes an assertion. A `RUN` continued across three lines is one
instruction whose second and third lines begin with `&&`; a blank line between
two of those lines does not end it; a BuildKit heredoc body is arguments to the
`RUN` that opened it and not instructions of its own; an `ONBUILD RUN` is a `RUN`
that executes in the next image; and a comment is dropped by Docker wherever it
appears, including between the lines of a continuation. A reader that got any of
those wrong would not report an error -- it would report *nothing*, which is the
shape of green a scan for absence must not be able to produce.

**Stages, because a flattened multi-stage file answers the wrong question.**
`instruction_lines` returns every instruction in the file, which is what the
migration scan wants: a migration in a discarded builder stage is still a
migration, and AD-22 holds "at any depth". The payload properties are the
opposite question -- what the *shipped* image declares -- and a `USER 1001` or an
`ENV HOME=/tmp` in a builder stage says nothing about it. `final_stage` is what
separates the two: the instructions from the last `FROM` onward, which is the
stage `docker build` produces by default.

A second reader would be the failure `tests/pixi_manifest.py` records for the
pixi manifest, arriving through the other file: two parsers that can disagree
about what an instruction *is*, so a line one module walks past is a line the
other's assertion never saw. This module is the parser Story 5.5 wrote,
promoted here when Story 5.6 needed it for a second set of assertions -- exactly
as Story 5.5 promoted the pixi-manifest reader rather than copying it.

Its own execution lives in `tests/unit/test_release_stage.py`, in
`test_the_dockerfile_parser_reads_each_form_an_instruction_can_take`: one case
per form an instruction can take, driven over synthetic text rather than over
whatever the repository's Dockerfile happens to contain today. That case is
where a regression in this file surfaces.

This is a helper module, not a collected one. `[tool.pytest.ini_options]
python_files` matches `test_*.py` and `tests.py`, so nothing here is collected,
and it sits at `tests/` rather than under `tests/unit/` for the reason
`tests/conftest.py` records: a collected test module is not a helper library, and
importing one from another ties two files' collection together.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING
from typing import Final

from tests.pixi_manifest import REPO_ROOT

if TYPE_CHECKING:
    from pathlib import Path

#: The file both readers open. Whatever `Dockerfile` is at the repository root,
#: with no path assumption beyond that -- and its absence is meaningful rather
#: than an error, because a materialized component ships none at all (AD-15).
DOCKERFILE: Final[Path] = REPO_ROOT / "Dockerfile"

#: The `Dockerfile`'s sibling, and `machinery` for the same reason it is. It
#: decides what the build context contains, which is the other half of "no
#: configuration file is present in the image": an enumerated `COPY` cannot bring
#: in what never reached the context, and this file is what keeps local state --
#: `.env`, `.envs/`, `.local-dev-keys/`, `db.sqlite3` -- out of it.
DOCKERIGNORE: Final[Path] = REPO_ROOT / ".dockerignore"

#: The container instructions that execute something. `FROM`, `COPY`, `ENV` and
#: the rest describe the image; these four describe what runs -- at build time,
#: at start-up and, for `HEALTHCHECK`, on an interval for the life of the
#: container.
#:
#: `ONBUILD` is not here because it is not an instruction of its own: it prefixes
#: one, and `instruction_lines` strips the prefix so the wrapped `RUN` or `CMD`
#: is classified as what it is.
EXECUTING_INSTRUCTIONS: Final[frozenset[str]] = frozenset({"RUN", "ENTRYPOINT", "CMD", "HEALTHCHECK"})

#: The instruction that opens a build stage. Every instruction after it belongs
#: to that stage and to no other, and the stage the last one opens is the image
#: `docker build` produces unless it is asked for a different `--target`.
FROM_INSTRUCTION: Final[str] = "FROM"

#: The `ONBUILD` prefix, the line continuation, and the comment marker Docker
#: strips wherever it appears -- including inside a continuation, which is why
#: the parser cannot gate the skip on being between instructions.
ONBUILD_INSTRUCTION: Final[str] = "ONBUILD"
CONTINUATION: Final[str] = "\\"
COMMENT_PREFIX: Final[str] = "#"

#: A BuildKit heredoc opener: `RUN <<EOF`, `RUN <<-EOF`, `RUN <<"EOF"`, and the
#: `cat > file <<EOF` form. The body that follows is arguments to the instruction
#: that opened it, not instructions of its own, and a line-per-instruction reader
#: would classify a command inside one under a head of `PIXI` and never scan it.
#: The delimiter word closes the body on a line of its own.
#:
#: Anchored to a *redirection* rather than to any `<<` in the text, and the
#: anchoring is what keeps the absorption from swallowing the rest of the file:
#: `RUN python -c "print(1 << shift)"` contains `<<` and opens no heredoc, and a
#: reader that treated it as one would classify every later instruction as body
#: and scan none of them. Three things are required, all of which a real opener
#: has and a shift operator does not -- the `<<` begins a word (start of line or
#: after whitespace, optionally behind a file-descriptor digit), the delimiter
#: follows it with no space, and the delimiter ends the word.
#:
#: Group 1 is the `-` of the `<<-` form, which strips *leading tabs* from the
#: body's terminator and from nothing else; group 3 is the delimiter word.
HEREDOC_OPENER: Final[re.Pattern[str]] = re.compile(r"(?:(?<=\s)|^)\d?<<(-?)(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\2(?=\s|$)")


def _closes_heredoc(line: str, delimiter: str, *, strip_tabs: bool) -> bool:
    """Report whether one raw line is the terminator of an open heredoc body.

    The comparison is against the *raw* line rather than a stripped one, because
    the shell's rule is positional: a terminator has to start at column zero. `
    EOF` indented inside a `RUN <<EOF` body is body text, and a reader that
    closed on it would end the instruction early and then classify the rest of
    the body -- `pixi run migrate`, say -- as instructions under a head nothing
    scans.

    The `<<-` form is the one exception and is exactly one exception: it strips
    *tabs*, not whitespace, from the front of the terminator. Spaces do not
    close a `<<-` body either.

    Args:
        line: The raw line, as the file spells it.
        delimiter: The delimiter word the opener named.
        strip_tabs: Whether the opener was the `<<-` form.

    Returns:
        True when this line closes the body.
    """
    candidate = line.lstrip("\t") if strip_tabs else line
    return candidate.rstrip() == delimiter


def _collected_instruction(start: int, parts: list[str]) -> tuple[int, str, str]:
    """Return one instruction's collected lines as (line number, instruction, arguments).

    Split on *any* whitespace rather than on a literal space. `RUN\tpixi run
    migrate` is a `RUN`, and a reader that partitioned on `" "` would classify it
    under a head of `RUN\tPIXI` -- outside `EXECUTING_INSTRUCTIONS`, outside
    every scan built on this parser, and reported by nothing.

    `ONBUILD` is stripped here rather than treated as an instruction of its own.
    It is a prefix: `ONBUILD RUN pixi run check` is a `RUN` that executes in the
    *next* image built from this one, and classifying it under a head of
    `ONBUILD` would put it outside `EXECUTING_INSTRUCTIONS` and outside every
    scan built on this parser.

    Args:
        start: The line number the instruction began on.
        parts: Its collected lines, continuations and heredoc body included.

    Returns:
        The instruction, upper-cased, with its arguments.
    """
    joined = " ".join(part for part in parts if part)
    head, arguments = _split_head(joined)
    while head == ONBUILD_INSTRUCTION and arguments:
        head, arguments = _split_head(arguments)
    return start, head, arguments


def _split_head(text: str) -> tuple[str, str]:
    """Split one instruction's text into its upper-cased head and its arguments.

    Args:
        text: The instruction's collected text.

    Returns:
        (head, arguments), both empty when the text carries neither.
    """
    parts = text.split(maxsplit=1)
    if not parts:
        return "", ""
    return parts[0].upper(), parts[1] if len(parts) > 1 else ""


def instruction_lines(dockerfile: str) -> list[tuple[int, str, str]]:
    """Return the Dockerfile's instructions as (line number, instruction, arguments).

    Five things happen here that a scan of raw lines does not do, and each of
    them is a way an instruction would otherwise escape the assertions built on
    this parser -- or be reported when it is not one.

    *Continuations are joined.* `RUN pixi run collectstatic \\` followed by `&&
    pixi run check` is one instruction, and a per-line reader would see a second
    line whose first word is `&&` and classify it as no instruction at all. An
    instruction whose last line is *itself* continued -- a trailing `\\` at end
    of file -- is still emitted, because dropping it would silently unscan
    whatever it ran.

    *A blank line inside a continuation does not end it.* Docker's own parser
    permits an empty continuation line and carries on; a reader that ended the
    instruction there would leave the following `&& pixi run migrate` parsed as
    an instruction whose head is `&&`, which nothing scans.

    *Comments are dropped wherever they appear*, including between the lines of
    a continuation, which is where Docker drops them too. Gating that on being
    between instructions is what turns a Dockerfile comment describing a
    prohibition into a reported breach of it: prose about a rule is not a
    violation of the rule, which is the same reason the entrypoint scan in
    `tests/unit/test_release_stage.py` parses Python rather than grepping it.

    *Heredoc bodies are absorbed into the instruction that opened them.* `RUN
    <<EOF` followed by a command is one `RUN`; read line by line, the body's
    first word is classified as an instruction nothing scans. The opener is
    matched as a redirection rather than as any `<<`, and the terminator has to
    stand at column zero -- see `HEREDOC_OPENER` and `_closes_heredoc` for the
    two ways a looser reader loses the rest of the file.

    Args:
        dockerfile: The file's text.

    Returns:
        One entry per instruction, the instruction upper-cased, in file order.
    """
    instructions: list[tuple[int, str, str]] = []
    pending: list[str] = []
    heredocs: list[tuple[str, bool]] = []
    continued = False
    start = 0
    for number, line in enumerate(dockerfile.splitlines(), start=1):
        stripped = line.strip()
        if heredocs:
            delimiter, strip_tabs = heredocs[0]
            if _closes_heredoc(line, delimiter, strip_tabs=strip_tabs):
                heredocs.pop(0)
                if not heredocs and not continued:
                    instructions.append(_collected_instruction(start, pending))
                    pending = []
            elif not stripped.startswith(COMMENT_PREFIX):
                pending.append(stripped)
            continue
        if stripped.startswith(COMMENT_PREFIX) or not stripped:
            # Blank inside a continuation as well as between instructions: the
            # `continued` flag is deliberately left as the previous line set it,
            # so the instruction stays open across the gap.
            continue
        if not pending:
            start = number
        continued = stripped.endswith(CONTINUATION)
        body = stripped.removesuffix(CONTINUATION).strip()
        pending.append(body)
        heredocs.extend((match.group(3), bool(match.group(1))) for match in HEREDOC_OPENER.finditer(body))
        if continued or heredocs:
            continue
        instructions.append(_collected_instruction(start, pending))
        pending = []
    if pending:
        instructions.append(_collected_instruction(start, pending))
    return instructions


def final_stage(instructions: list[tuple[int, str, str]]) -> list[tuple[int, str, str]]:
    """Return the instructions of the stage the image is actually built from.

    A multi-stage build ships the last stage and discards the rest. Read flat, a
    `USER 1001` and an `ENV HOME=/tmp` in a builder stage satisfy every
    payload-property assertion while the stage that ships runs as root with
    `HOME=/`, so the properties have to be read off the stage that survives.

    The opposite is true of the migration scan, which is why it does not use
    this: a migration in a discarded builder stage is still a migration, and
    AD-22 holds "at any depth".

    A file with no `FROM` at all is returned whole rather than empty. That is a
    fragment rather than a Dockerfile, and returning nothing would make every
    assertion of absence built on it pass by having nothing to read -- the exact
    vacuity the callers' own guards exist to prevent.

    Args:
        instructions: The parsed instructions, as `instruction_lines` returns.

    Returns:
        The instructions from the last `FROM` onward, inclusive.
    """
    opened = [index for index, (_number, head, _arguments) in enumerate(instructions) if head == FROM_INSTRUCTION]
    if not opened:
        return list(instructions)
    return list(instructions[opened[-1] :])
