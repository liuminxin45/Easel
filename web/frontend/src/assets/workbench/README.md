# Project skill avatar

`oil-pig-avatar.jpg` is a byte-for-byte copy of the original user avatar:
`D:/Projects/neo-content/资料/风格研究/2026-10-20-精致武侠小猪/用户原始头像.jpg`
(original source filename: `头像.jpg`, 162025 bytes).
The original file is unchanged. The SVG displays the complete square image;
it does not redraw, recolor or crop the character.
Source and copy SHA256:
`fada68aa7ebdf42b9dd89f4650013b0c0ba54b867776f6ab02a9f1ee31a095b1`.
Tests verify this fixed SHA against the repository copy and do not require
the external source directory on another machine.
The build inlines the JPEG in its cached JavaScript because the existing native
static server does not serve `.jpg` files. This preserves the bytes, requires no
backend change, and makes the avatar available with the offline frontend bundle.

All seven project skills share this single bundled image. Their independent
bottom-right purpose marks use the existing 24-unit SVG grid and currentColor.
Official general and platform skill icons retain their original mappings.
