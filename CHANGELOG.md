# Changelog

All notable changes to RhinoClaw will be documented in this file.

## [0.2.3] - 2026-03-21

### Added
- Embedded Chat Panel (ClawChat) with configurable AI backends
- 72 Tools: Full geometry, transform, boolean, material, Grasshopper support
- PBR Material support with full property control
- GrasshopperPlayer automation with parameter passing
- Viewport screenshots with annotations
- Solid AI branding throughout

### Changed
- Improved WebSocket event streaming reliability
- Better error handling for long-running operations

## [0.2.0] - 2026-03-16

### Added
- SentinelChat Panel embedded in Rhino 8
- Remote access support via Tailscale
- Grasshopper Definition Builder
- WebSocket client for real-time event monitoring

### Changed
- Upgraded TCP protocol for better stability
- Improved Grasshopper parameter handling

## [0.1.0] - 2026-01-28

### Added
- Initial release
- Basic geometry creation (sphere, box, cylinder, cone, torus, pipe)
- Layer management (create, delete, set current)
- Material assignment (basic + PBR)
- TCP Server connection on port 1999
- Grasshopper integration (SDK + Player)
- Boolean operations (union, difference, intersection, split)
- Import/Export support (3dm, obj, stl, step, iges)
