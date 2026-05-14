"""
Proposed contention-aware task duplication scheduler (CA-D).

Main contribution of the project. Evaluates parent duplication candidates
using tentative scheduling under the contention-aware NoC communication model.
Applies duplication only when Delta_EFT = EFT_no_dup - EFT_dup > 0.
Uses bottom-level priority (Sinnen et al., 2011).
Implemented in Phase 8.
"""
