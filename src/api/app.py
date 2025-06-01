from typing import List
import concurrent.futures
from flask import Flask, jsonify, request, Response, stream_with_context
from flask_cors import CORS
import html
import json
from search import SearchAllStage, WebSearchDocument
from search_session import SearchSession, DOMAINS_ALLOW,  JSON_STREAM_SEPARATOR
import time
import asyncio

app = Flask(__name__)
CORS(app, resources={r"/stream_search": {"origins": DOMAINS_ALLOW}})


class StreamSearchResponse:
    def __init__(self, success: bool, stage: SearchAllStage, num_tokens_used: int, websearch_docs: List[WebSearchDocument], answer="") -> None:
        self.success = success
        self.stage = stage
        self.num_tokens_used = num_tokens_used
        self.websearch_docs = websearch_docs
        self.answer = answer

    def to_json_data(self):
        return (json.dumps({
                    'success': self.success,
                    'stage': self.stage.value,
                    'num_tokens_used': self.num_tokens_used,
                    'websearch_docs': [doc.to_dict() for doc in self.websearch_docs],
                    'answer': self.answer
        }) + JSON_STREAM_SEPARATOR).encode('utf-8') 

@app.route('/stream_search', methods=['POST'])
def stream_search():
    data = request.get_json()
    user_prompt = data.get('user_prompt')
    expand_query = data.get('expand_query',False)
    allow_web_search = data.get('allow_web_search',True)
    allow_local_search = data.get('allow_local_search',True)
    print("stream_search query:", user_prompt)
    if not user_prompt:
        return jsonify({'success': False, 'message': 'Please provide a user prompt.'})
    def generate():
        
        session = SearchSession(query=user_prompt, allow_local_search = allow_local_search, web_search_enabled=allow_web_search,personality="Professional",max_depth=3)
    

        # loop = asyncio.get_event_loop()
        # final_answer = loop.run_until_complete(session.run_session())

        # # Save final report
        # output_path = session.save_report(final_answer)
        # print(f"[INFO] Final report saved to: {output_path}")
        yield StreamSearchResponse(success=True, stage=SearchAllStage.STARTING, num_tokens_used=0, websearch_docs=[]).to_json_data()
        
        plain_enhanced_query = session.clean_search_query(session.enhanced_query)

        subqueries = session.generate_subqueries(plain_enhanced_query)

        yield StreamSearchResponse(success=True, stage=SearchAllStage.EXPANDING_QUERY, num_tokens_used=0, websearch_docs=[]).to_json_data()

        subqueries = session.maybe_monte_carlo(subqueries,plain_enhanced_query)

        yield StreamSearchResponse(success=True, stage=SearchAllStage.SELECTING_SUBQUERIES, num_tokens_used=0, websearch_docs=[]).to_json_data()
        
        if session.web_search_enabled and session.max_depth >= 1:
            yield StreamSearchResponse(success=True, stage=SearchAllStage.SEARCHING_WEB, num_tokens_used=0, websearch_docs=[]).to_json_data()

        if session.web_search_enabled and session.max_depth >= 1:
            loop = asyncio.get_event_loop()
            loop.run_until_complete(session.run_web_search(subqueries))
            yield StreamSearchResponse(success=True, stage=SearchAllStage.DOWNLOADED_WEBPAGES, num_tokens_used=0, websearch_docs=[]).to_json_data()

        if session.local_search_enabled:
            yield StreamSearchResponse(success=True, stage=SearchAllStage.SEARCHING_LOCAL, num_tokens_used=0, websearch_docs=[]).to_json_data()
            session.run_local_search(subqueries)
            yield StreamSearchResponse(success=True, stage=SearchAllStage.READING_LOCAL_KNOWLEDGE, num_tokens_used=0, websearch_docs=[]).to_json_data()
        
        yield StreamSearchResponse(success=True, stage=SearchAllStage.READING_WEBPAGES_AND_LOCAL, num_tokens_used=0, websearch_docs=[]).to_json_data()

        
        loop = asyncio.get_event_loop()
        final_answer = loop.run_until_complete(session.generate_final_answer())

        # Save final report
        output_path = session.save_report(final_answer)

        yield StreamSearchResponse(success=True, stage=SearchAllStage.RESULTS_READY, num_tokens_used=session.num_tokens_used, websearch_docs=session.web_results, answer=final_answer).to_json_data()


    return Response(stream_with_context(generate()), mimetype='application/json')



# @app.route('/document-indexer', methods=['POST'])
# def documentindexer():
#     data = request.get_json()
#     user_prompt = data.get('user_prompt')
#     print_log("document-indexer:", user_prompt)
#     if not user_prompt:
#         return jsonify({'success': False, 'message': 'Please provide a user prompt.'}), 400

#     def long_running_task(prompt):
#         # Simulate a long-running task (replace with your actual logic)
#         print_log(f"Started long-running task for: {prompt}")
#         time.sleep(30)  # Simulate work
#         print_log(f"Completed long-running task for: {prompt}")

#     # Start the long-running task in a background thread
#     executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
#     executor.submit(long_running_task, user_prompt)

#     return jsonify({'success': True, 'message': 'Task started.', }), 202

# ...existing code...

if __name__ == "__main__":
    # app.run(debug=False, host='0.0.0.0', port=80)
    app.run(debug=False)