# Standard library imports
import os
import tempfile
import time
from typing import List
import streamlit as st
import xlsxwriter
from io import BytesIO
import base64
import requests
import tempfile
import os
import json
import time

# Third-party imports
import camelot
import openai
import re
from openai import OpenAI as OpenAIclient
import streamlit as st

# Local application/library specific imports
from llama_hub.file.pymu_pdf.base import PyMuPDFReader
from llama_index import Document, QueryBundle, VectorStoreIndex, ServiceContext
from llama_index.llms import OpenAI
from llama_index.node_parser import SentenceSplitter
from llama_index.query_engine import PandasQueryEngine, RetrieverQueryEngine
from llama_index.readers.schema.base import Document
from llama_index.retrievers import (
    BaseRetriever, VectorIndexRetriever, KeywordTableSimpleRetriever, RecursiveRetriever
)
from llama_index.response_synthesizers import get_response_synthesizer
from llama_index.schema import NodeWithScore, IndexNode
from llmsherpa.readers import LayoutPDFReader

from collections import defaultdict


os.environ['OPENAI_API_KEY'] = st.secrets["OPENAI_API_KEY"]
openai.api_key = st.secrets["OPENAI_API_KEY"]

class CustomRetriever(BaseRetriever):
    """Custom retriever that performs both semantic search and hybrid search."""

    def __init__(
        self,
        vector_retriever: VectorIndexRetriever,
        keyword_retriever: KeywordTableSimpleRetriever,
        mode: str = "AND",
    ) -> None:
        """Init params."""

        self._vector_retriever = vector_retriever
        self._keyword_retriever = keyword_retriever
        if mode not in ("AND", "OR"):
            raise ValueError("Invalid mode.")
        self._mode = mode

    def _retrieve(self, query_bundle: QueryBundle) -> List[NodeWithScore]:
        """Retrieve nodes given query."""

        vector_nodes = self._vector_retriever.retrieve(query_bundle)
        keyword_nodes = self._keyword_retriever.retrieve(query_bundle)

        vector_ids = {n.node.node_id for n in vector_nodes}
        keyword_ids = {n.node.node_id for n in keyword_nodes}

        combined_dict = {n.node.node_id: n for n in vector_nodes}
        combined_dict.update({n.node.node_id: n for n in keyword_nodes})

        if self._mode == "AND":
            retrieve_ids = vector_ids.intersection(keyword_ids)
        else:
            retrieve_ids = vector_ids.union(keyword_ids)

        retrieve_nodes = [combined_dict[rid] for rid in retrieve_ids]
        return retrieve_nodes


# Function to encode the image
def encode_image(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')

def save_uploaded_file(uploaded_file):
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(uploaded_file.name)[1]) as tmp_file:
            tmp_file.write(uploaded_file.getvalue())
            return tmp_file.name
    except Exception as e:
        st.error(f"Error saving file {uploaded_file.name}: {e}")
        return None

# Function to extract data with retry mechanism
def safely_extract_data(image_path, max_retries=3, delay=5):
    attempts = 0
    while attempts < max_retries:
        try:
            base64_image = encode_image(image_path)
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {st.secrets['OPENAI_API_KEY']}"
            }
            payload = {
                "model": "gpt-4-vision-preview",
                "messages": [
                    {
                        "role": "system",
                        "content": "You are a helpful assistant designed to output JSON."
                    },
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": "Extract text from this image of a business card, output JSON of Company Name, Contact Name, Position, City/State, Address, Phone Number, Email Address, Website, Notes. Leave as blank if not found."
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{base64_image}"
                                }
                            }
                        ]
                    }
                ],
                "max_tokens": 300
            }
            response = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload)
            if response.status_code == 200:
                response_data = response.json()
                content = response_data['choices'][0]['message']['content']

                # Check if content is wrapped with Markdown code block delimiters for JSON
                if content.startswith('```json') and content.endswith('```'):
                    # Strip the Markdown ```json and ``` characters
                    content = content[7:-4].strip()
                elif content.startswith('{') and content.endswith('}'):
                    # It's already a JSON string, so just strip leading/trailing whitespace
                    content = content.strip()

                # Now try to parse the cleaned string as JSON
                try:
                    content_data = json.loads(content)
                except json.JSONDecodeError as e:
                    raise ValueError(f"Failed to parse JSON content: {e}")

                return content_data
            else:
                raise Exception(f"API request failed with status code: {response.status_code}")
        except Exception as e:
            st.error(f"Attempt {attempts + 1} failed: {e}")
            attempts += 1
            time.sleep(delay)
    return None

company_information_questions = {
    "Company": "name of the company.",
    "Comments": "analyze comparison to competitors.",
    "Overview": "Provide a detailed summary and overview of the company.",
    "Patents:": "Patents or FDA process.",
    "Last Financing": "last financing round, amount, and date.",
    "Investment Stage:": "List investment stages (e.g., Seed, Series A, Series B, Series C, IPO)?  ",
    "Last Deal Details": {
        "Post Valuation": "post-valuation: <<$XX.XXmm (MM/DD/YY)>>  ",
        "Total Raised to Date": "Total Raised to Date: <<$XX.XXmm (MM/DD/YY)>>  ",
        "Market Cap": "market capitalization or Market Cap: <<$XX.XXmm (MM/DD/YY)>>  ",
        "EV": "Enterprise Value (EV): Example format <<$XX.XXmm (MM/DD/YY)>>  "
    },
    "TTM Total Revenue": "Revenue or Trailing Twelve Months total revenue.  ",
    "TTM EBITDA": "EBITDA or Trailing Twelve Months EBITDA.  ",
    "Investors:": "investors names?  ",
    "Board of Directors:": "All of the board Members and their roles.",
    "Website": "url, website link, www.",
    "C-Suite": "founders, CEO, CFO, Chief Officers, etc.",
    "Email": "email address.  ",
    "Phone:": "phone number.  ",
    "Street Address": "address.  ",
    "City": "contact information: city.  ",
    "State": "contact information: state.  ",
    "Zip:": "contact information: ZIP code.  ",
    "News Alert": "latest news, headline",
    "Prospecting Topic List": "keywords, topics, and phrases",
    "Email Template for Prospecting": "Subject: Financial Solutions Tailored for [Company Name] in the [Sub-Sector] Space\n\nDear [Prospect's Name],\n\nI hope this message finds you well. I was intrigued by [Company Name]'s recent accomplishments in [Sub-Sector]. As part of our startup and middle-market banking division at [Your Bank's Name], we specialize in offering customized financial solutions that could help accelerate your growth.\n\nCould we schedule a brief call this week to explore how we can assist in your financial strategies?\n\nBest Regards,\n[Your Name]\n[Your Position]\n[Your Bank's Name]\n[Contact Details]",
    "Sector Tags": "use company overview to determine if it is one of the following: #BioPharma, #MedTech, #HealthcareIT, #Diagnostics, #MedicalTools, or other #",
    "General Tags": "Use general tags to broadly classify the company's overarching themes and applicable markets. Start with a high-level sector tag and include additional tags that capture the company's main functions, methodologies, and target audience or market. Examples of general tags include: - Operational focus: #Startup, #SME, #LargeScale, #ResearchInstitute  - Technological capabilities: #AI, #MachineLearning, #BigData, #Robotics, #WearableTech  - Research and development areas: #DrugDevelopment, #ClinicalTrials, #GeneticEngineering, #RegenerativeMedicine  - Patient and disease focus: #PatientCare, #ChronicIllness, #RareDiseases, #MentalHealth, #InfectiousDiseases  - Market and user application: #ConsumerHealth, #B2B, #ClinicianTools, #PatientEngagement, #HealthcareAnalytics - The purpose of these general tags is to provide a quick snapshot of the company's role and relevance in the broader industry context. They should be selected to convey the widest reach of the company’s impact without going into the specific details of their products or services.",
}


from llama_index.llms import OpenAI 
llm = OpenAI(temperature=0, model="gpt-4-1106-preview")
service_context = ServiceContext.from_defaults(llm=llm)

def save_uploaded_file(uploaded_file):
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(uploaded_file.name)[1]) as tmp_file:
            tmp_file.write(uploaded_file.getvalue())
            return tmp_file.name
    except Exception as e:
        st.error(f"Error saving file {uploaded_file.name}: {e}")
        return None

# Function to set the column width to fit the content
def auto_size_columns(worksheet):
    for column in worksheet.columns:
        max_length = max(len(str(cell.value)) for cell in column if cell.value) + 2
        worksheet.column_dimensions[column[0].column_letter].width = max_length

# Function to generate responses based on company information prompts
def query_company_data(query_engine, prompts_dict, responses):
    for column_name, prompt in prompts_dict.items():
        if isinstance(prompt, dict):
            query_company_data(query_engine, prompt, responses)  # Recursive call for nested prompts
        else:
            # Query the engine and store the response
            response = query_engine.query(prompt)
            responses[column_name] = str(response)  # Use .text or the appropriate attribute to extract the text


def get_tables(path: str, pages: List[int]):
    table_dfs = []
    for page in pages:
        # Read tables from the specified page
        table_list = camelot.read_pdf(path, pages=str(page))

        # Check if any tables were found
        if len(table_list) > 0:
            table_df = table_list[0].df

            # Process the table as before
            table_df = (
                table_df.rename(columns=table_df.iloc[0])
                .drop(table_df.index[0])
                .reset_index(drop=True)
            )
            table_dfs.append(table_df)
        else:
            print(f"No tables found on page {page}")

    return table_dfs


def summarize_table(table_df):
    """
    Generate a summary for a given table.
    :param table_df: pandas DataFrame
    :return: Summary string
    """
    # Convert the table to a string or a format that GPT can understand
    table_json = table_df.to_json(orient="split")
    print("\n\n table_json \n", table_json)
    
    client = OpenAIclient()

    # Use GPT to generate a summary title for the table
    # Adjust the prompt as necessary for your use case
    response = client.chat.completions.create(
        model="gpt-4-1106-preview",
        messages=[
            {"role": "system", "content": "Summarize the table's usage as a table title with table in json format below:"},
            {"role": "user", "content": str(table_json)},
        ]
        ,
    )
    return str(response.choices[0].message.content.strip())


########### End of setting for query engine ############

# st.session_state variables
if st.session_state.get("all_documents_node_storage") is None:
    st.session_state.all_documents_node_storage = defaultdict(list)
if st.session_state.get("global_df_id_query_engine_mapping") is None:
    st.session_state.global_df_id_query_engine_mapping = defaultdict(dict)
if st.session_state.get("all_responses") is None:
    st.session_state.all_responses = []
if st.session_state.get("selected_doc") is None:
    st.session_state.selected_doc = None
if 'processed_files' not in st.session_state:
    st.session_state.processed_files = set()
if 'file_path_unix' not in st.session_state:
    st.session_state.file_path_unix = []
else:
    print("\nst.session_state.file_path_unix", st.session_state.file_path_unix)
if 'company_name' not in st.session_state:
    st.session_state.company_name = []
else:
    print("\nst.session_state.company_name", st.session_state.company_name)

with st.sidebar:
    st.header("Business Card -> Contact List Excel Download")
    st.subheader("Upload business card images to extract contact information and download as excel.")
    uploaded_files = st.file_uploader("Choose an image file", accept_multiple_files=True)

    if st.button("Generate COI excel file"):
        all_extracted_data = []
        for uploaded_file in uploaded_files:
            file_path = save_uploaded_file(uploaded_file)
            if file_path:
                extracted_data = safely_extract_data(file_path)
                if extracted_data:
                    all_extracted_data.append(extracted_data)
                else:
                    st.error(f"Data extraction failed for {uploaded_file.name} after retries.")
                os.remove(file_path)  # Clean up the temp file

        # Create a workbook and add a worksheet
        output = BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        worksheet = workbook.add_worksheet()

        # Check if all_extracted_data is not empty before proceeding
        if all_extracted_data:
            # Write headers to the first row
            headers = all_extracted_data[0].keys()  # Assuming all items have the same structure
            for col, header in enumerate(headers):
                worksheet.write(0, col, header)
                worksheet.set_column(col, col, len(header) * 2)

            # Write data starting from the second row
            for row, data in enumerate(all_extracted_data, start=1):
                for col, (key, value) in enumerate(data.items()):
                    worksheet.write(row, col, value)

            # Close the workbook to write the data to the in-memory string
            workbook.close()

            # Create the download button
            st.download_button(
                label="Download Excel workbook",
                data=output.getvalue(),
                file_name="business_card_data.xlsx",
                mime="application/vnd.ms-excel"
            )
        else:
            st.error("No data to write to Excel.")


    st.divider() ### Below is reserved for "PDF Reader & Feed Your Banking Chatbot"

    st.header("Pitchbook or Company Info PDF -> Excel")
    st.subheader("Upload PDF files to extract company information and download as excel with portfolio tracker template.")

    uploaded_files = st.file_uploader("Upload PDF files", accept_multiple_files=True, type=['pdf'])


    # Process uploaded files
    if st.button("Process PDF Documents") and uploaded_files:
        start_time = time.time()

        for uploaded_file in uploaded_files:
            file_identifier = uploaded_file.name
            if file_identifier not in st.session_state.processed_files:
                # Save uploaded file to a temporary path
                with st.spinner(f'Processing {uploaded_file.name}...'):
                    file_path = save_uploaded_file(uploaded_file)
                    print(file_path)
                    st.session_state.file_path_unix.append(file_path.replace('C:', '').replace('\\', '/'))
                    print(st.session_state.file_path_unix[-1])
                    st.session_state.company_name.append(uploaded_file.name)
                    print(st.session_state.company_name[-1])

                    ##### Experiment with parser 1 #####
                    reader = PyMuPDFReader()
                    docs = reader.load(st.session_state.file_path_unix[-1])
                    print("\n\n docs \n", docs)

                    total_pages = docs[0].metadata.get("total_pages",0)
                    total_pages_list = []
                    for i in range(total_pages):
                        total_pages_list.append(i)
                    print("\n\n total_pages_list \n", total_pages_list)                

                    table_dfs = get_tables(st.session_state.file_path_unix[-1], pages=total_pages_list)
                    print("\n\n tables \n", table_dfs)

                    ##### Experiment with parser 2 #####
                    llmsherpa_api_url = "https://readers.llmsherpa.com/api/document/developer/parseDocument?renderFormat=all"
                    pdf_path = st.session_state.file_path_unix[-1]
                    pdf_reader = LayoutPDFReader(llmsherpa_api_url)
                    doc = pdf_reader.read_pdf(pdf_path)
                    print("\n\nDebug doc:\n", doc.tables())

                    raw_nodes = []
                    for idx, chunk in enumerate(doc.chunks()):
                        print(Document(text=chunk.to_context_text(), extra_info={}), "\n")
                        raw_nodes.append(Document(doc_id=f"{st.session_state.company_name[-1]} pdf layout {idx}", text=chunk.to_context_text(), extra_info={}))


                    ##### define query engines over these tables #####

                    # define query engines over these tables
                    from llama_index.llms import OpenAI
                    llm = OpenAI(temperature=0, model="gpt-4-1106-preview")

                    service_context = ServiceContext.from_defaults(llm=llm)
                    df_query_engines = [
                        PandasQueryEngine(table_df, service_context=service_context)
                        for table_df in table_dfs
                    ]

                    node_parser = SentenceSplitter(chunk_size=1024, chunk_overlap=20)

                    doc_nodes = node_parser.get_nodes_from_documents(
                        documents=docs, show_progress=False
                    )
                    
                    print("\n\n doc_nodes \n", doc_nodes)
                    print("\n\n table_dfs \n", table_dfs)

                    # define index nodes
                    summaries = [summarize_table(table_df) for table_df in table_dfs]

                    df_nodes = [
                        IndexNode(text=summary, index_id=f"{st.session_state.company_name[-1]} pandas{idx}")
                        for idx, summary in enumerate(summaries)
                    ]
                    print("\n\n df_nodes \n", df_nodes)

                    df_id_query_engine_mapping = {
                        f"{st.session_state.company_name[-1]} pandas{idx}": df_query_engine
                        for idx, df_query_engine in enumerate(df_query_engines)
                    }

                    ##### chatv1 #####
                    # store mapping for later use
                    st.session_state.global_df_id_query_engine_mapping[st.session_state.company_name[-1]].update(df_id_query_engine_mapping)
                    st.session_state.global_df_id_query_engine_mapping["all"].update(df_id_query_engine_mapping)

                    # Aggregate nodes for company-wide query engine
                    st.session_state.all_documents_node_storage[st.session_state.company_name[-1]].extend(doc_nodes + df_nodes + raw_nodes)
                    st.session_state.all_documents_node_storage["all"].extend(doc_nodes + df_nodes + raw_nodes)

                    ##### End #####


                    # construct top-level vector index + query engine
                    vector_index = VectorStoreIndex(doc_nodes + df_nodes + raw_nodes)
                    vector_retriever = vector_index.as_retriever(similarity_top_k=2)
                    
                    from llama_index.retrievers import RecursiveRetriever
                    from llama_index.query_engine import RetrieverQueryEngine
                    from llama_index.response_synthesizers import get_response_synthesizer

                    recursive_retriever = RecursiveRetriever(
                        "vector",
                        retriever_dict={"vector": vector_retriever},
                        query_engine_dict=df_id_query_engine_mapping,
                        verbose=True,
                    )

                    response_synthesizer = get_response_synthesizer(
                        # service_context=service_context,
                        response_mode="compact"
                    )

                    query_engine = RetrieverQueryEngine.from_args(
                        recursive_retriever, response_synthesizer=response_synthesizer
                    )


                    ##### End of experiment with keyword retriever #####

                    responses = {}
                    query_company_data(query_engine, company_information_questions, responses)  # Generate responses
                    st.session_state.all_responses.append(responses)

                    st.success(f"Processed {uploaded_file.name}!")
                    st.session_state.processed_files.add(file_identifier)
            else:
                st.info(f'Skipped processing for {uploaded_file.name} as it was already processed.')

        import xlsxwriter
        from io import BytesIO
        # Create a workbook and add a worksheet
        output = BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        worksheet = workbook.add_worksheet()

        # Check if all_responses is not empty before proceeding
        if st.session_state.all_responses:
            # Write headers to the first row
            headers = st.session_state.all_responses[0].keys()  # Assuming all items have the same structure
            for col, header in enumerate(headers):
                worksheet.write(0, col, header)
                worksheet.set_column(col, col, len(header) * 2)

            # Write data starting from the second row
            for row, data in enumerate(st.session_state.all_responses, start=1):
                for col, (key, value) in enumerate(data.items()):
                    worksheet.write(row, col, value)

            # Close the workbook to write the data to the in-memory string
            workbook.close()

            # Create the download button
            st.download_button(
                label="Download Processed Excel",
                data=output.getvalue(),
                file_name="company_pitchbook_info_hybrid_search.xlsx",
                mime="application/vnd.ms-excel"
            )
            st.success("Processing complete! "+ str(time.time() - start_time) + " seconds")
        else:
            st.error("No data to write to Excel.")

client = OpenAIclient()
openai.api_key = st.secrets["OPENAI_API_KEY"]

document_analysis_system_prompt = (
    "If no information is found, then inform the user to upload a new document.\n\n"
    "Analyze and extract key information from financial and company-related documents. Focus on providing concise, relevant, and accurate data extracted from the documents.\n"
    "Document Understanding: Deeply analyze the content of the documents to understand the context and specifics of the company information.\n"
    "Precision in Data Extraction: Extract precise data points, financial figures, and other relevant information from the documents.\n"
    "Summarization Skills: Summarize the content of the documents, highlighting the key points and essential information in a concise manner.\n"
    "Relevancy Check: Ensure that the responses are directly relevant to the user's queries about the document's content.\n"
    "Financial Knowledge: Apply understanding of financial terms and concepts to interpret the data accurately.\n"
    "Clarity and Coherence: Provide clear and coherent responses that make the extracted information easy to understand.\n"
    "Engagement in Document Analysis: Show engagement and proficiency in handling complex financial documents to assist users in their analysis.\n\n"
    "In essence, the system should assist in dissecting complex documents, pulling out vital information, and presenting it in a user-friendly manner, aligning with the queries made by the user.\n\n"
    "GUIDELINES:\n"
    "1. Understand the context of the user's query in relation to the document.\n"
    "2. Focus on extracting and summarizing relevant information from the document that answers the user's query.\n"
    "3. Offer insights and summaries based on the content of the documents, utilizing financial acumen.\n"
    "4. Maintain clarity and precision in responses, ensuring that they are informative and directly related to the query."
)


def summarize_all_messages(message):
    # write function to summarize all messages to extract the main points
    summarization = client.chat.completions.create(
        model="gpt-4-1106-preview",
        messages=[
            {"role": "system", "content": 'List out key points from conversation:'},
            {"role": "user", "content": message},
        ],
    )
    text = summarization.choices[0].message.content.strip()
    text = re.sub("\s+", " ", text)
    return text
        

def specific_query_response(query):
    # query the engine and store the response
    query_engine_responses = query_engine.query(query)
    print("\nquery_company_data responses", query_engine_responses)
    # add company data to the session state
    st.session_state.company_data.append(query_engine_responses)
    # add company data to the chat memory
    st.session_state.chat_convo_memory.append({"role": "company_data", "content": query_engine_responses})
    # openai streaming response after querying for specific document response
    full_response = ""
    for response in client.chat.completions.create(
        model="gpt-4-1106-preview",
        messages=[
            {"role": "system", "content": document_analysis_system_prompt},
            {"role": "user", "content": query},
        ],
        stream=True,
    ):
        full_response += str(response.choices[0].delta.content)
        message_placeholder.markdown(full_response + "▌")
    # add assistant messages
    st.session_state.messages.append({"role": "assistant", "content": full_response})
    message_placeholder.markdown(st.session_state.messages[-1]["content"])
    # add both user and assistant (last two) messages to the chat memory
    st.session_state.chat_convo_memory.append("".join([str(st.session_state.messages[-2]), str(st.session_state.messages[-1])]))
    # summarize the entire conversation for the session to extract the main points
    st.session_state.summary.append(summarize_all_messages("".join([str(st.session_state.chat_convo_memory)])))

def summary_query_response(query):
    # given the document path and the company name, read the document and summarize it
    # if all is selected then all documents will be summarized
    selected_doc = st.session_state.selected_doc
    if selected_doc == "all":
        # summarize all documents
        all_documents_node_storage = st.session_state.all_documents_node_storage
        all_documents = all_documents_node_storage["all"]
        print("\nall_documents", all_documents)
        # summarize all documents
        all_document_text = ""
        for document in all_documents:
            all_document_text += document.text
        print("\nall_document_text", all_document_text)
        # summarize all documents
        summarization = client.chat.completions.create(
            model="gpt-4-1106-preview",
            messages=[
                {"role": "system", "content": 'Summarize the content of all documents:'},
                {"role": "user", "content": query},
            ],
        )
        text = summarization.choices[0].message.content.strip()
        text = re.sub("\s+", " ", text)
        # add assistant messages
        st.session_state.messages.append({"role": "assistant", "content": text})
        message_placeholder.markdown(st.session_state.messages[-1]["content"])
        # add both user and assistant (last two) messages to the chat memory
        st.session_state.chat_convo_memory.append("".join([str(st.session_state.messages[-2]), str(st.session_state.messages[-1])]))
        # summarize the entire conversation for the session to extract the main points
        st.session_state.summary.append(summarize_all_messages("".join([str(st.session_state.chat_convo_memory)])))
    else:
        # summarize the selected document
        all_documents_node_storage = st.session_state.all_documents_node_storage
        selected_document = all_documents_node_storage[selected_doc]
        print("\nselected_document", selected_document)
        # summarize the selected document
        selected_document_text = ""
        for document in selected_document:
            selected_document_text += document.text
        print("\nselected_document_text", selected_document_text)
        # summarize the selected document
        summarization = client.chat.completions.create(
            model="gpt-4-1106-preview",
            messages=[
                {"role": "system", "content": 'Summarize the content of the selected document:'},
                {"role": "user", "content": query},
            ],
        )
        text = summarization.choices[0].message.content.strip()
        text = re.sub("\s+", " ", text)
        # add assistant messages
        st.session_state.messages.append({"role": "assistant", "content": text})
        message_placeholder.markdown(st.session_state.messages[-1]["content"])
        # add both user and assistant (last two) messages to the chat memory
        st.session_state.chat_convo_memory.append("".join([str(st.session_state.messages[-2]), str(st.session_state.messages[-1])]))
        # summarize the entire conversation for the session to extract the main points
        st.session_state.summary.append(summarize_all_messages("".join([str(st.session_state.chat_convo_memory)])))
    
st.container()

query_engine = None

st.header("Chat with your PDFs!")
st.subheader("Select your PDF document to chat with.")
st.write("Only support chatting with either 'all' or one document at a time.")
st.write("'all' works best with a single document domain.")
print("\nall_documents_node_storage.keys()", list(st.session_state.all_documents_node_storage.keys()))

options = list(st.session_state.all_documents_node_storage.keys())
st.session_state.selected_doc = st.selectbox("Select a document or all", options, index=options.index(st.session_state.selected_doc) if st.session_state.selected_doc in options else 0)
selected_doc = st.session_state.selected_doc

# selected_doc = st.selectbox("Select a document or all", options=list(all_documents_node_storage.keys()))
print("\nselected_doc", selected_doc)

company_vector_index = VectorStoreIndex(st.session_state.all_documents_node_storage[selected_doc])
company_vector_retriever = company_vector_index.as_retriever(similarity_top_k=2)

# Ensure this is a dictionary
query_engine_dict = st.session_state.global_df_id_query_engine_mapping.get(selected_doc, {})

# Debugging: Check the type of query_engine_dict
print("\nType of query_engine_dict:", type(query_engine_dict))

recursive_retriever = RecursiveRetriever(
    "vector",
    retriever_dict={"vector": company_vector_retriever},
    query_engine_dict=query_engine_dict,
    verbose=True,
)
response_synthesizer = get_response_synthesizer(
    # service_context=service_context,
    response_mode="compact"
)

query_engine = RetrieverQueryEngine.from_args(
    recursive_retriever, response_synthesizer=response_synthesizer
)


if st.session_state.get("messages") is None:
    # add user or assistant messages
    st.session_state.messages = []
if st.session_state.get("chat_convo_memory") is None:
    # add all outputs to the chat memory and label properly according to context
    st.session_state.chat_convo_memory = []
if st.session_state.get("summary") is None:
    # chat session summary: summarize the entire conversation to list the main points
    st.session_state.summary = []
    st.session_state.summary.append("")
if st.session_state.get("company_data") is None:
    # store company data pulled from the PDFs
    st.session_state.company_data = []
    st.session_state.company_data.append("")

if query := st.chat_input("What would you like to learn from your PDF/s?"):
    # add user messages
    st.session_state.messages.append({"role": "user", "content": query})
    query_dict = {"user query": query} # for query_company_data function  
    print("\nquery_dict", query_dict)
    with st.chat_message("user"):
        st.markdown(st.session_state.messages[-1]["content"])

    with st.chat_message("assistant"):                
        # Use the selected query engine
        message_placeholder = st.empty()
        full_response_first_message = ""
        for response in client.chat.completions.create(
            model="gpt-3.5-turbo-1106",
            messages=[
                {"role": "system", "content": f"Appreicate user for the document selected: {selected_doc}. Ask user to wait while data processing is happening. Then assist user by providing a summary with summary_query_response if user asks to 'Provide a summary for selected document or all adocuments, such as when user asks 'summarize', 'tell me about the document' or 'what is this document about'.'. Or provide 'specific document detail, not for 'tell me about the document' or 'summarize all documents' using function specific_query_response' Otherwise, respond as usual with system promt: {document_analysis_system_prompt}"},
                {"role": "user", "content": query},
            ],
            stream=True,
        ):
            full_response_first_message += str(response.choices[0].delta.content)
            message_placeholder.markdown(full_response_first_message + "▌")
        st.session_state.messages.append({"role": "assistant", "content": full_response_first_message})
        message_placeholder.markdown(st.session_state.messages[-1]["content"])

        assistant_messages = [{"role": "user", "content": f"User Need: {query}"}]
        print("\nassistant_messages", assistant_messages)
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "specific_query_response",
                    "description": "specific document detail, not for 'tell me about the document' or 'summarize all documents'.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "The user's query for detailed information."
                            }
                        },
                        "required": ["query"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "summary_query_response",
                    "description": "Provide a summary for selected document or all adocuments, such as when user asks 'summarize', 'tell me about the document' or 'what is this document about'.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "The user's query for a summary of the document(s)."
                            }
                        },
                        "required": ["query"]
                    }
                }
            }
        ]
        tool_call_response = client.chat.completions.create(
            model="gpt-3.5-turbo-1106",
            messages=assistant_messages,
            tools=tools,
            tool_choice="auto",  # auto is default, but we'll be explicit
        )
        tool_call_response_message = tool_call_response.choices[0].message
        print("\ntool_call_response_message", tool_call_response_message)
        tool_calls = tool_call_response_message.tool_calls

        if tool_calls:
            available_functions = {
                "specific_query_response": specific_query_response,
                "summary_query_response": summary_query_response,
            }
            assistant_messages.append({"role": "assistant", "content": tool_call_response_message.content})  # extend conversation with assistant's reply
            st.session_state.messages.append({"role": "assistant", "content": tool_call_response_message.content})
            st.markdown(st.session_state.messages[-1]["content"])

            for tool_call in tool_calls:
                function_name = tool_call.function.name
                function_to_call = available_functions.get(function_name)
                if function_to_call:
                    function_args = json.loads(tool_call.function.arguments)
                    function_response = function_to_call(**function_args)
                    assistant_message = {
                        "tool_call_id": tool_call.id,
                        "role": "function",
                        "name": function_name,
                        "content": function_response,
                    }
                    assistant_messages.append(assistant_message)  # extend conversation with function response
                    # append:
                    # {"role": "system", "content": "Chat Session Summary (Track progress of conversation): " + str(st.session_state.summary[-1])},
                    # {"role": "system", "content": "Latest Company Data from PDF (Check if any new updates): " + str(st.session_state.company_data[-1])},                    
                    assistant_messages.append({"role": "system", "content": "Chat Session Summary (Track progress of conversation): " + str(st.session_state.summary[-1])})
                    assistant_messages.append({"role": "system", "content": "Latest Company Data from PDF (Check if any new updates): " + str(st.session_state.company_data[-1])})
                    print("\nassistant_messages before second response", assistant_messages)
                    st.session_state.messages.append({"role": "assistant", "content": assistant_message["content"]})
                    st.markdown(st.session_state.messages[-1]["content"])

            second_response = client.chat.completions.create(
                model="gpt-4-1106-preview",
                messages=[{"role": "assistant", "content": str(assistant_messages)}],
            )  # get a new response from the model where it can see the function response
            st.session_state.messages.append({"role": "assistant", "content": second_response.choices[0].message.content.strip()})
            st.markdown(st.session_state.messages[-1]["content"])
            print("\nsecond_response content:", st.session_state.messages[-1]["content"])
              

# Reset Button
if st.button("Reset Button"):
    with st.sidebar:
        st.session_state.messages = []
        st.session_state.chat_convo_memory = []
        st.session_state.summary = []
        st.session_state.company_data = []
        st.session_state.selected_doc = None
        st.session_state.processed_files = set()
        st.session_state.all_documents_node_storage = defaultdict(list)
        st.session_state.global_df_id_query_engine_mapping = defaultdict(dict)
        st.session_state.all_responses = []
