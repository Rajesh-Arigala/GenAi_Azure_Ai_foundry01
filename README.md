## Run this:

```
sudo rm /etc/apt/sources.list.d/yarn.list 2>/dev/null
sudo apt update

Then install Azure CLI again:

curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash

az version
az login 

```


from openai import AzureOpenAI

endpoint = "https://rag-11111-resource.cognitiveservices.azure.com/"
embedding_deployment = "text-embedding-3-small"

client = AzureOpenAI(
    api_version="2024-12-01-preview",
    azure_endpoint=endpoint,
    api_key=loaded_config["AZURE_OPENAI_API_KEY"],
)

response = client.embeddings.create(
    input=["Today is a good day", "second phrase", "third phrase"],
    model=embedding_deployment,
)

for item in response.data:
    length = len(item.embedding)
    print(
        f"data[{item.index}]: length={length}, "
        f"[{item.embedding[0]}, {item.embedding[1]}, "
        f"..., {item.embedding[length - 2]}, {item.embedding[length - 1]}]"
    )

print(response.usage)
