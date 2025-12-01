# Markdown Syntax Guide

## Headings

```markdown
# H1 - Largest heading
## H2 - Second level
### H3 - Third level
#### H4 - Fourth level
##### H5 - Fifth level
###### H6 - Smallest heading
```

## Text Formatting

```markdown
**Bold text**
*Italic text*
***Bold and italic***
~~Strikethrough~~
`Inline code`
```

**Bold text**  
*Italic text*  
***Bold and italic***  
~~Strikethrough~~  
`Inline code`

## Lists

### Unordered Lists
```markdown
- Item 1
- Item 2
  - Nested item 2.1
  - Nested item 2.2
- Item 3
```

- Item 1
- Item 2
  - Nested item 2.1
  - Nested item 2.2
- Item 3

### Ordered Lists
```markdown
1. First item
2. Second item
3. Third item
   1. Nested item 3.1
   2. Nested item 3.2
```

1. First item
2. Second item
3. Third item
   1. Nested item 3.1
   2. Nested item 3.2

## Links

```markdown
[Link text](https://example.com)
[Link with title](https://example.com "Hover text")
```

[Link text](https://example.com)  
[Link with title](https://example.com "Hover text")

## Images

```markdown
![Alt text](image-url.jpg)
![Alt text](image-url.jpg "Optional title")
```

## Code Blocks

### Inline Code
```markdown
Use `code` for inline code
```

Use `code` for inline code

### Code Blocks with Syntax Highlighting
````markdown
```python
def hello_world():
    print("Hello, World!")
```

```javascript
function helloWorld() {
    console.log("Hello, World!");
}
```

```bash
git add .
git commit -m "message"
```
````

## Blockquotes

```markdown
> This is a blockquote
> It can span multiple lines
>> Nested blockquote
```

> This is a blockquote  
> It can span multiple lines
>> Nested blockquote

## Horizontal Rules

```markdown
---
***
___
```

---

## Tables

```markdown
| Header 1 | Header 2 | Header 3 |
|----------|----------|----------|
| Row 1    | Data     | Data     |
| Row 2    | Data     | Data     |
| Row 3    | Data     | Data     |
```

| Header 1 | Header 2 | Header 3 |
|----------|----------|----------|
| Row 1    | Data     | Data     |
| Row 2    | Data     | Data     |
| Row 3    | Data     | Data     |

### Aligned Tables

```markdown
| Left aligned | Center aligned | Right aligned |
|:-------------|:--------------:|--------------:|
| Left         | Center         | Right         |
| Data         | Data           | Data          |
```

| Left aligned | Center aligned | Right aligned |
|:-------------|:--------------:|--------------:|
| Left         | Center         | Right         |
| Data         | Data           | Data          |

## Task Lists

```markdown
- [x] Completed task
- [ ] Incomplete task
- [ ] Another task
  - [x] Nested completed
  - [ ] Nested incomplete
```

- [x] Completed task
- [ ] Incomplete task
- [ ] Another task
  - [x] Nested completed
  - [ ] Nested incomplete

## Emojis (GitHub)

```markdown
:smile: :heart: :fire: :rocket: :star:
🔥 💯 ⚡ ✨ 🚀
```

:smile: :heart: :fire: :rocket: :star:  
🔥 💯 ⚡ ✨ 🚀

## HTML in Markdown

```markdown
<details>
<summary>Click to expand</summary>

Hidden content here

</details>
```

<details>
<summary>Click to expand</summary>

Hidden content here

</details>

## Badges (GitHub)

```markdown
![Build Status](https://img.shields.io/badge/build-passing-brightgreen)
![License](https://img.shields.io/badge/license-MIT-blue)
![Python](https://img.shields.io/badge/python-3.10+-blue)
```

![Build Status](https://img.shields.io/badge/build-passing-brightgreen)
![License](https://img.shields.io/badge/license-MIT-blue)
![Python](https://img.shields.io/badge/python-3.10+-blue)

## Footnotes

```markdown
Here's a sentence with a footnote[^1].

[^1]: This is the footnote content.
```

Here's a sentence with a footnote[^1].

[^1]: This is the footnote content.

## Definition Lists

```markdown
Term
: Definition of the term

Another term
: Definition of another term
```

## Escaping Characters

```markdown
\* Not italic \*
\# Not a heading
\[Not a link\](url)
```

\* Not italic \*  
\# Not a heading  
\[Not a link\](url)

## Line Breaks

```markdown
Line 1  
Line 2 (two spaces at end of Line 1)

Line 3

Line 4 (blank line between)
```

Line 1  
Line 2 (two spaces at end of Line 1)

Line 3

Line 4 (blank line between)

## Comments (GitHub)

```markdown
<!-- This is a comment and won't be visible -->
```

<!-- This is a comment and won't be visible -->

## GitHub-Specific Features

### Mentions
```markdown
@username
```

### Issue/PR References
```markdown
#123
username/repo#123
```

### Commit References
```markdown
commit-sha
username@commit-sha
username/repo@commit-sha
```

### Keyboard Keys
```markdown
<kbd>Ctrl</kbd> + <kbd>C</kbd>
```

<kbd>Ctrl</kbd> + <kbd>C</kbd>

## YAML Frontmatter (Hugging Face)

```markdown
---
title: Project Name
emoji: 🔥
colorFrom: red
colorTo: blue
sdk: docker
pinned: false
---

# Your content starts here
```

## Tips for Good README

1. **Start with a clear title** using `#`
2. **Add badges** for build status, license, etc.
3. **Include sections**: Features, Installation, Usage, API
4. **Use code blocks** with syntax highlighting
5. **Add images/GIFs** to demonstrate features
6. **Create a table of contents** for long docs
7. **Include contributing guidelines**
8. **Add license information**

## Example README Structure

```markdown
# Project Name

Brief description

## Features
- Feature 1
- Feature 2

## Installation
```bash
pip install package
```

## Usage
```python
import package
package.do_something()
```

## API Reference
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api`   | GET    | Get data    |

## Contributing
Pull requests welcome!

## License
MIT
```