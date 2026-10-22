# Noncommercial PM skill pack (opt-in)

This directory holds the CC BY-NC-SA 4.0 methods. They are **not** covered by the repository's MIT license in `../../LICENSE`.

- `investigation/SKILL.md` (id `looop:investigation`) — adaptation of `autonomous-investigation` from Dean Peters, Product-Manager-Skills.
- `competitive-research/SKILL.md` (id `looop:competitive-research`) — adaptation of `competitive-research-snapshot` from the same repository.

Attribution: Dean Peters, [Product-Manager-Skills](https://github.com/deanpeters/Product-Manager-Skills), CC BY-NC-SA 4.0. Original copyright, the reviewed originals and the full license text are in `pm-skills/upstream/deanpeters/` (`upstream/deanpeters/LICENSE`), repo-relative, with the LICENSE also reachable from here as `../upstream/deanpeters/LICENSE`; no upstream endorsement is implied. Adaptations remain CC BY-NC-SA 4.0: noncommercial use, attribution, and share-alike on distribution of modified material.

Both `SKILL.md` files were moved here from `pm-skills/investigation/` and `pm-skills/competitive-research/`. Their footer links (`../upstream/deanpeters/skills/...`) were written relative to that old location and no longer resolve; the files are kept byte-identical on purpose because manifest.json pins their sha256. Follow those links under `pm-skills/upstream/deanpeters/` instead.

## Enabling the pack

The loader and the Magpie export include these skills only when `data/local-settings.json` at the runtime root contains:

```json
{"pm_skills": {"noncommercial": true}}
```

Missing file, missing key, a non-`true` value or unparsable JSON keeps the pack disabled; the MIT method `looop:research-core` is the default research protocol instead.

## Scope

Methods return caller-owned state and never extend project authority. Project-owned methods take precedence. Enabling the pack does not change scheduling, scope approval or execution rights, and does not authorize redistribution under MIT.
