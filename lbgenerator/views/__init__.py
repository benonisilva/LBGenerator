from ..lib import utils
from .security import verify_api_key
from pyramid.response import Response
from pyramid.exceptions import HTTPNotFound
from pyramid_restler.view import RESTfulView
from pyramid.httpexceptions import HTTPFound

from ..lib import utils


def response_callback(request, response):

    # NOTE: Tentar fechar a conexão de qualquer forma!
    # -> Na criação da conexão "coautocommit=True"!
    # By Questor
    try:
        if self.context.session.is_active:
            self.context.session.close()
    except:
        pass

    if 'callback' in request.params:
        response.text=request.params['callback'] + '(' + response.text + ')'


class CustomView(RESTfulView):
    """ Default Customized View Methods.
    """

    def __init__(self, context, request):
        self.context=context
        self.request=request
        self.request.add_response_callback(response_callback)
        self.base_name=self.request.matchdict.get('base')

    @verify_api_key
    def get_base(self):
        """Return Base object
        """

        return self.context.get_base()

    @verify_api_key
    def set_base(self, base_json):
        """Set Base object
        """

        return self.context.set_base(base_json)

    @verify_api_key
    def get_collection(self, render_to_response=True):
        """ Search database objects.

        @param render_to_response: Se deseja que a saída seja 
        renderizada.
        """

        params=self.request.params.get('$$', '{}')
        query=utils.json2object(params)
        try:
            collection=self.context.get_collection(query)
        except Exception as e:

            # NOTE: Tentar fechar a conexão de qualquer forma!
            # -> Na criação da conexão "coautocommit=True"!
            # By Questor
            try:
                if self.context.session.is_active:
                    self.context.session.close()
            except:
                pass

            raise Exception('SearchError: %s' % e)
        else:
            # NOTE: Entra no "else" sempre que não entrar no "except".
            # diferente de "finally" que sempre ocorre! By Questor

            if render_to_response:

                # NOTE: "collection" está dentro de um padrão de 
                # "RESTfulView" que é herdado! By Questor

                # NOTE: Se já não houver nada definido na requizição p/ 
                # a renderização, redenderiza uma resposta de "acordo" 
                # com o que for possível definir (um "best_match") 
                # conforme o header da requizição privilegiando o 
                # formato 'application/json' e depois 'application/xml'!
                # By Questor

                # NOTE: Renderizar p/ a resposta html... By Questor
                response=self.render_to_response(collection)

            else:

                # NOTE: Sem renderizar p/ a resposta html... By Questor
                response=collection

        # NOTE: Tentar fechar a conexão de qualquer forma!
        # -> Na criação da conexão "coautocommit=True"!
        # By Questor
        try:
            if self.context.session.is_active:
                self.context.session.close()
        except:
            pass

        return response

    @verify_api_key
    def get_member(self):
        id=self.request.matchdict['id']
        self.wrap=False
        member=self.context.get_member(id)
        return self.render_to_response(member)

    @verify_api_key
    def create_member(self):
        member=self.context.create_member(self._get_data())
        id=self.context.get_member_id_as_string(member)

        try:
            try:
                content=value["value"]
                RobotInterface.baseContentSaveLight(
                    self.request.matchdict["base"], 
                    content, 
                    id
                )
            except Exception as e:
                RobotInterface.baseStructSaveLight(
                    value["name"], 
                    value["struct"]
                )

        except Exception as e:
            pass

        # NOTE: Tentar fechar a conexão de qualquer forma!
        # -> Na criação da conexão "coautocommit=True"!
        # By Questor
        try:
            if self.context.session.is_active:
                self.context.session.close()
        except:
            pass

        return self.render_custom_response(id, default_response=id)

    @verify_api_key
    def update_member(self):
        id=self.request.matchdict['id']
        member=self.context.get_member(id, close_sess=False)
        if member is None:

            # NOTE: Tentar fechar a conexão de qualquer forma!
            # -> Na criação da conexão "coautocommit=True"!
            # By Questor
            try:
                if self.context.session.is_active:
                    self.context.session.close()
            except:
                pass

            raise HTTPNotFound()

        self.context.update_member(member, self._get_data(member))

        # NOTE: Tentar fechar a conexão de qualquer forma!
        # -> Na criação da conexão "coautocommit=True"!
        # By Questor
        try:
            if self.context.session.is_active:
                self.context.session.close()
        except:
            pass

        return self.render_custom_response(id, default_response='UPDATED')

    @verify_api_key
    def delete_member(self):
        id=self.request.matchdict['id']
        is_deleted=self.context.delete_member(id)

        # NOTE: Check if the number of deleted rows is different than 0!
        # By John Doe
        if is_deleted.__dict__['rowcount'] == 0:

            # NOTE: Tentar fechar a conexão de qualquer forma!
            # -> Na criação da conexão "coautocommit=True"!
            # By Questor
            try:
                if self.context.session.is_active:
                    self.context.session.close()
            except:
                pass

            raise HTTPNotFound()

        # NOTE: Tentar fechar a conexão de qualquer forma!
        # -> Na criação da conexão "coautocommit=True"!
        # By Questor
        try:
            if self.context.session.is_active:
                self.context.session.close()
        except:
            pass

        return Response('DELETED', charset='utf-8', status=200, content_type='')

    def render_custom_response(self, id, default_response):
        _return=self.request.params.get('return', '')
        is_valid_return=hasattr(self.context.entity, _return)
        if is_valid_return:
            member=self.context.get_member(id)
            response_attr=getattr(member, _return)
            return Response(str(response_attr), charset='utf-8', status=200, content_type='application/json')
        else:
            return Response(default_response, charset='utf-8', status=200, content_type='')

    @verify_api_key
    def get_collection_cached(self, render_to_response=True):
        """Return document collection in cache

        :param render_to_response: Should we render or return JSON
        :return: Document HTML or JSON
        """

        params=self.request.params.get('$$', '{}')

        # NOTE: Cache key concerning expiring time! By John Doe
        cache_type=self.request.params.get('cache_key', 'default_term')
        cache_key=self.request.current_route_path()
        query=utils.json2object(params)

        try:
            collection=self.context.get_collection_cached(query, cache_key, cache_type)
        except Exception as e:

            # NOTE: Tentar fechar a conexão de qualquer forma!
            # -> Na criação da conexão "coautocommit=True"!
            # By Questor
            try:
                if self.context.session.is_active:
                    self.context.session.close()
            except:
                pass

            raise Exception('SearchError: %s' % e)
        else:
            if render_to_response:
                response=self.render_to_response(collection)
            else:
                response=collection

        # NOTE: Tentar fechar a conexão de qualquer forma!
        # -> Na criação da conexão "coautocommit=True"!
        # By Questor
        try:
            if self.context.session.is_active:
                self.context.session.close()
        except:
            pass

        return response

    @verify_api_key
    def get_member_cached(self):
        """Get member cached.
        """

        id=self.request.matchdict['id']
        cache_key=self.request.current_route_path()
        self.wrap=False

        # NOTE: Get cached member! By John Doe
        member=self.context.get_member_cached(id, cache_key)

        # NOTE: Tentar fechar a conexão de qualquer forma!
        # -> Na criação da conexão "coautocommit=True"!
        # By Questor
        try:
            if self.context.session.is_active:
                self.context.session.close()
        except:
            pass

        return self.render_to_response(member)
