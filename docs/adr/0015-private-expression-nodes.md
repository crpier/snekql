# Keep concrete query expression nodes private

Public expression names are non-constructible annotations; model methods, column methods, and Query Builder factories alone create private concrete nodes. This preserves useful owner/result typing without letting callers forge operands or state that Query Compilation would otherwise trust. Read-only `ColumnRef` remains public because comparison and projection give it useful helper-seam depth, while assignment stays on concrete model columns.
