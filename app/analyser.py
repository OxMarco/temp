from typing import List
from pydantic import BaseModel

class PictureDescription(BaseModel):
    """
    Defines the structure of the expected response content when describing an image:
    - name: The object's name.
    - description: A short description of the object.
    - fun_facts: A list of funny facts about the object.
    """
    name: str
    description: str
    fun_facts: List[str]

class FridgeRecipesList(BaseModel):
    recipes: List[str]
    ingredients: List[str]
    links: List[str]

def process_image_recognition(client, lang, image):
  completion = client.beta.chat.completions.parse(
    model="gpt-4o-2024-08-06",
    messages=[{
      "role": "user",
      "content": [{
        "type": "text",
          "text": (
            f"Describe the object in the image, tell me its name, "
            f"describe it and give three funny facts about it. "
            f"Use a simple language, use {lang} only"
          )},
          {
            "type": "image_url",
            "image_url": {
              "url": f"data:image/jpeg;base64,{image}"
            }
          }]
        }],
        response_format=PictureDescription,
        max_tokens=500
  )

  return completion.choices[0].message

def process_fridge_analysis(client, lang, image):
  pass
