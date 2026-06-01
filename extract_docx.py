import zipfile
import xml.etree.ElementTree as ET
import os

def docx_to_text(path):
    try:
        with zipfile.ZipFile(path) as z:
            xml_content = z.read('word/document.xml')
            root = ET.fromstring(xml_content)
            
            # XML Namespaces
            ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
            
            paragraphs = []
            # We want to find all paragraph elements
            for paragraph in root.findall('.//w:p', ns):
                texts = []
                for run in paragraph.findall('.//w:r', ns):
                    for text_elem in run.findall('.//w:t', ns):
                        if text_elem.text:
                            texts.append(text_elem.text)
                paragraphs.append(''.join(texts))
            return '\n'.join(paragraphs)
    except Exception as e:
        return f"Error reading {path}: {str(e)}"

def convert_all():
    files = ["SentiStream_PRD.docx", "SentiStream_TRD.docx", "SentiStream_IPD.docx"]
    for file in files:
        if os.path.exists(file):
            print(f"Extracting {file}...")
            text = docx_to_text(file)
            out_name = file.replace(".docx", ".txt")
            with open(out_name, "w", encoding="utf-8") as f:
                f.write(text)
            print(f"Saved to {out_name} (Length: {len(text)} chars)")
        else:
            print(f"File {file} not found")

if __name__ == "__main__":
    convert_all()
