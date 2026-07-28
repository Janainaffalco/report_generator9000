# Montserrat source record

- Origin: Boilerplate
- Family: Montserrat variable, upright weight axis
- Upstream: https://github.com/google/fonts/tree/76fca9fd0bb4ea46583f92e978660f3984ab9442/ofl/montserrat
- Upstream revision: `76fca9fd0bb4ea46583f92e978660f3984ab9442` (2024-10-21)
- Source file: `Montserrat[wght].ttf`
- Local file: `Montserrat-wght.ttf`
- SHA-256: `0f7b311b2f3279e4eef9b2f968bcdbab6e28f4daeb1f049f4f278a902bcd82f7`
- License: SIL Open Font License 1.1; see `OFL.txt`

`Montserrat-wght.ttf` is a variable font; Word embeds a static face per
`embedRegular`, and the face's own `name` table must match the `w:font
w:name` that references it. Word will not consume the variable font itself
as an embedded face, and its own internal family name (`Montserrat Thin`,
its default `wght` instance) matches none of the five faces the document
asks for by direct or style formatting.

Each static instance below was produced with `fontTools.varLib.instancer`
(`instantiateVariableFont`, pinning `wght`), with its `name` table rewritten
so name ID 1 (and 4) read the exact face name `master.py` embeds it under.
Only the master's built parts embed these; `Montserrat-wght.ttf` is kept
here solely as the instancing source of record.

| Local file | Face (`w:font w:name`) | `wght` | SHA-256 |
| --- | --- | --- | --- |
| `Montserrat-Regular.ttf` | `Montserrat` | 400 | `8cc4cb81935311185adafe64363cd84e0ea5d8a6d8e66af58e87daa406e0e008` |
| `Montserrat-Medium.ttf` | `Montserrat Medium` | 500 | `1f0a1e0472cf2652cd6629b603fbec8001409dce41d1fbc1057cd0b8e06691a5` |
| `Montserrat-Light.ttf` | `Montserrat Light` | 300 | `516dbc5299fd4e5e8074a30df5ad9e223c853d0e828444357a8ad2c57b87743a` |
| `Montserrat-ExtraLight.ttf` | `Montserrat ExtraLight` | 200 | `46636ac6fa02b06fab955113465fde32eef9d70acb5abd1e84059c9abc0a276e` |
| `Montserrat-Black.ttf` | `Montserrat Black` | 900 | `7ad3bb6f694c06521e7bb280dfc356e9844b850a365d7ad8640f459d7dc5588e` |

`master.py` embeds only the faces whose `w:rFonts/@w:ascii` actually appears
across `word/document.xml`, `word/header*.xml`, and `word/footer*.xml` in
the built Master -- currently all five, but a face this document stops
using is dropped rather than shipped unused.

The exact upstream `METADATA.pb` is retained beside the font and license.
