# Coding agent host protocols

`stdio.py` is the versioned JSONL boundary for desktop and other external
hosts. The coding agent owns execution and persisted checkpoints. A host owns
its composer queue and submits a single prompt per active turn.

Protocol version 1 advertises `runs`, `resume`, `interrupt`, `input`, `models`,
and `images` in its `ready` frame. A host sends `run`, `answer`, or `interrupt`
commands and reads `event`, `input_requested`, `error`, and `done` frames.
Unknown control-plane events can be ignored without losing the terminal
`done` frame. A later version must change the version number when it changes
required frame semantics.
