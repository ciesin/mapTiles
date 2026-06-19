To generate a maplibre-spec spritesheet for webmap icons, use the *spreet* CLI tool.

Save icons e.g., SVG, in a single folder, then input it to spreet and define an output name:

`spreet --sdf --retina --unique --minify-index-file  maki/ output/maki@2x`

`spreet --sdf --unique --minify-index-file  maki/ output/maki`

remove `--minify-index-file` to pretty-print the index json