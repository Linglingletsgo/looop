"""Inside the network namespace: expose only this run's model socket on loopback."""
import socket,socketserver,threading
class Relay(socketserver.BaseRequestHandler):
 def handle(self):
  upstream=socket.socket(socket.AF_UNIX);upstream.connect('/gateway/model.sock')
  def pump(a,b):
   try:
    while chunk:=a.recv(65536): b.sendall(chunk)
   except OSError: pass
   finally:
    try:b.shutdown(socket.SHUT_WR)
    except OSError:pass
  t=threading.Thread(target=pump,args=(self.request,upstream),daemon=True);t.start();pump(upstream,self.request);t.join();upstream.close()
class Server(socketserver.ThreadingTCPServer):allow_reuse_address=True;daemon_threads=True
Server(('127.0.0.1',8317),Relay).serve_forever()
