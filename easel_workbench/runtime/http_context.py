"""In-process response adapter for existing login forms.

These domain renderers retain their validation; this class opens no socket.
"""
import io,email.message
from fastapi.responses import Response

class Context:
    def __init__(self,method,target,headers,body=b''):
        self.command=method;self.path=target;self.headers=email.message.Message()
        for key,value in headers:self.headers[key]=value
        self.rfile=io.BytesIO(body);self.wfile=io.BytesIO();self.code=200;self.response_headers=[]
    def send_response(self,code):self.code=code
    def send_header(self,key,value):self.response_headers.append((key,value))
    def end_headers(self):pass
    def auth_event(self,*args):pass
    def response(self):
        r=Response(self.wfile.getvalue(),status_code=self.code)
        r.raw_headers=[(k.lower().encode('latin1'),v.encode('latin1')) for k,v in self.response_headers if k.lower()!='connection']
        return r
